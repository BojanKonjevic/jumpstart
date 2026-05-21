"""Remove-addon pipeline — undoes a single addon applied to an existing project."""

from __future__ import annotations

import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import tomlkit
import typer
import yaml
from tomlkit.items import Array

from zenit.addons._registry import get_available_addons
from zenit.addons.checks import check_can_remove
from zenit.cli.prompt import prompt_single_addon
from zenit.cli.ui import (
    DIM,
    RED,
    RESET,
    addon_summary,
    bullet_list,
    dry_header,
    dry_run_banner,
    error,
    info,
    success,
    warn,
)
from zenit.core.handlers import HandlerDispatcher
from zenit.core.handlers.justfile_handler import _RECIPE_NAME_RE
from zenit.core.lockfile import ZenitLockfile, read_lockfile, write_lockfile
from zenit.core.manifest import (
    read_manifest,
    remove_blocks_for_addon,
    write_manifest,
)
from zenit.core.pkg_name import normalise_pkg_name, resolve_dest_placeholder
from zenit.core.render import build_render_vars, make_env
from zenit.schema.exceptions import ZenitError
from zenit.schema.models import AddonConfig


def remove_addon(
    addon_id: str, dry_run: bool = False, project_dir: Path | None = None
) -> None:
    """Remove a single addon from an existing zenit project."""

    if project_dir is None:
        project_dir = Path.cwd()
    available = get_available_addons()

    lockfile = check_can_remove(project_dir, addon_id, available)

    template = lockfile.template
    pkg_name = normalise_pkg_name(project_dir.name)
    addon_cfg = next(cfg for cfg in available if cfg.id == addon_id)

    if dry_run:
        _dry_remove(project_dir, addon_id, addon_cfg, lockfile, pkg_name)
        return

    addon_summary("remove", addon_id, project_dir, template)

    if sys.stdin.isatty():
        try:
            raw = input(f"  Proceed? {DIM}[Y/n]{RESET}  ").strip().lower()
        except EOFError, KeyboardInterrupt:
            print()
            raise typer.Exit(0) from None
        if raw not in ("", "y", "yes"):
            warn("Aborted.")
            raise typer.Exit(0)
    else:
        warn("Non-interactive mode — proceeding automatically.")

    render_vars = build_render_vars(
        name=project_dir.name,
        pkg_name=pkg_name,
        template=template,
        has_postgres=template == "fastapi",
        has_redis="redis" in lockfile.addons,
        addons=lockfile.addons,
    )

    # ── files ──────────────────────────────────────────────────────────────
    removed_files = _remove_files(project_dir, addon_cfg, pkg_name)

    # ── injections (physical removal only — manifest written at the end) ────
    _undo_injections_physical(project_dir, addon_cfg)

    # ── compose services ────────────────────────────────────────────────────
    removed_services = _remove_compose_services(project_dir, addon_cfg)
    _remove_compose_volumes(project_dir, addon_cfg)

    # ── env vars ─────────────────────────────────────────────────────────────
    removed_env_vars = _remove_env_vars(project_dir, addon_cfg)

    # ── deps ──────────────────────────────────────────────────────────────
    removed_deps, removed_dev_deps = _remove_deps(project_dir, addon_cfg)

    # ── justfile recipes ──────────────────────────────────────────────────
    removed_recipes = _remove_just_recipes(project_dir, addon_cfg, render_vars)

    # ── manifest (written once, after all physical removals succeed) ────────
    manifest = read_manifest(project_dir)
    remove_blocks_for_addon(manifest, addon_id)
    write_manifest(project_dir, manifest)

    # ── lockfile ──────────────────────────────────────────────────────────
    new_addons = [a for a in lockfile.addons if a != addon_id]
    write_lockfile(project_dir, template, new_addons)

    # ── output ────────────────────────────────────────────────────────────
    print()
    success(f"Addon '{addon_id}' removed from '{project_dir.name}'.")

    if removed_files:
        bullet_list("Files removed:", removed_files, bullet="-", bullet_color=RED)

    if removed_deps or removed_dev_deps:
        bullet_list("Dependencies removed from pyproject.toml:", removed_deps, bullet="-", bullet_color=RED)
        if removed_dev_deps:
            bullet_list("", removed_dev_deps, bullet="-", bullet_color=RED, suffix="(dev)")
        info("Run 'uv sync' to uninstall them.")

    if removed_recipes:
        bullet_list("Just recipes removed:", removed_recipes, bullet="-", bullet_color=RED)

    if removed_services:
        bullet_list("Compose services removed:", removed_services, bullet="-", bullet_color=RED)

    if removed_env_vars:
        bullet_list("Env vars removed:", removed_env_vars, bullet="-", bullet_color=RED)

    print()


# ── Removal helpers ───────────────────────────────────────────────────────────


def _remove_files(
    project_dir: Path, addon_cfg: AddonConfig, pkg_name: str
) -> list[str]:
    """Delete files that were created by this addon. Returns list of removed paths."""

    all_dests = {resolve_dest_placeholder(fc.dest, pkg_name) for fc in addon_cfg.files}

    removed: list[str] = []

    for fc in addon_cfg.files:
        dest = resolve_dest_placeholder(fc.dest, pkg_name)
        full = project_dir / dest

        if dest.endswith("__init__.py") and fc.content == "":
            parent = full.parent
            siblings_on_disk = (
                {
                    p.relative_to(project_dir).as_posix()
                    for p in parent.iterdir()
                    if p.is_file() and p != full
                }
                if parent.exists()
                else set()
            )
            surviving_siblings = siblings_on_disk - all_dests
            if surviving_siblings:
                continue

        if full.exists():
            full.unlink()
            removed.append(dest)
            _prune_empty_parents(full.parent, project_dir)

    return removed


def _prune_empty_parents(directory: Path, stop_at: Path) -> None:
    """Remove empty directories walking upward, stopping at stop_at."""
    while directory != stop_at and directory.is_relative_to(stop_at):
        try:
            if not any(directory.iterdir()):
                directory.rmdir()
                directory = directory.parent
            else:
                break
        except OSError:
            break


def _undo_injections_physical(
    project_dir: Path,
    addon_cfg: AddonConfig,
) -> None:
    """Physically remove all Python blocks injected by *addon_cfg*.

    Reads the current manifest to find recorded blocks, dispatches each to
    the appropriate handler's remove(), and stops.  It does NOT mutate or
    write the manifest — that is the caller's responsibility, once all other
    physical removals have also succeeded.  This keeps manifest writes atomic
    with respect to the full removal sequence.
    """

    manifest = read_manifest(project_dir)
    dispatcher = HandlerDispatcher()

    for block in list(manifest.python_blocks):
        if block.addon != addon_cfg.id:
            continue
        file_path = project_dir / block.file
        if not file_path.exists():
            print(
                f"Warning: '{block.file}' is missing — skipping removal of "
                f"'{block.point}' injection for addon '{addon_cfg.id}'. "
                f"Run 'zenit doctor' to verify project integrity.",
                file=sys.stderr,
            )
            continue
        dispatcher.remove(file_path, block)


def _remove_compose_services(
    project_dir: Path,
    addon_cfg: AddonConfig,
) -> list[str]:
    """Remove compose services that belong to this addon. Returns removed service names."""

    compose_path = project_dir / "compose.yml"
    if not compose_path.exists() or not addon_cfg.compose_services:
        return []

    data: dict[str, Any] = (
        yaml.safe_load(compose_path.read_text(encoding="utf-8")) or {}
    )
    services: dict[str, Any] = data.get("services", {})

    removed: list[str] = []
    for svc in addon_cfg.compose_services:
        if svc.name in services:
            del services[svc.name]
            removed.append(svc.name)

    if removed:
        compose_path.write_text(
            yaml.dump(data, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )

    return removed


def _remove_compose_volumes(project_dir: Path, addon_cfg: AddonConfig) -> None:
    """Remove named volumes that belong to this addon from compose.yml."""

    compose_path = project_dir / "compose.yml"
    if not compose_path.exists() or not addon_cfg.compose_volumes:
        return

    data: dict[str, Any] = (
        yaml.safe_load(compose_path.read_text(encoding="utf-8")) or {}
    )
    vols: dict[str, Any] = data.get("volumes", {})

    changed = False
    for vol_name in addon_cfg.compose_volumes:
        if vol_name in vols:
            del vols[vol_name]
            changed = True

    if changed:
        compose_path.write_text(
            yaml.dump(data, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )


def _remove_env_vars(project_dir: Path, addon_cfg: AddonConfig) -> list[str]:
    """Remove env var lines owned by this addon. Returns removed keys."""

    if not addon_cfg.env_vars:
        return []

    keys_to_remove = {v.key for v in addon_cfg.env_vars}
    removed: list[str] = []

    for file_name in (".env", ".env.example"):
        env_path = project_dir / file_name
        if not env_path.exists():
            continue
        lines = env_path.read_text(encoding="utf-8").splitlines(keepends=True)
        new_lines: list[str] = []
        for line in lines:
            if "=" not in line:
                new_lines.append(line)
                continue
            key = line.split("=", 1)[0].strip()
            if key in keys_to_remove:
                removed.append(key)
                continue
            new_lines.append(line)
        env_path.write_text("".join(new_lines), encoding="utf-8")

    return removed


def _remove_deps(
    project_dir: Path, addon_cfg: AddonConfig
) -> tuple[list[str], list[str]]:
    """Remove deps contributed by this addon from pyproject.toml.

    Returns (removed_deps, removed_dev_deps).
    """

    pyproject_path = project_dir / "pyproject.toml"
    if not pyproject_path.exists():
        return [], []

    doc = tomlkit.parse(pyproject_path.read_text(encoding="utf-8"))

    def _normalise(dep: str) -> str:
        return re.split(r"[>=<!,; \[]", dep)[0].lower().replace("-", "_")

    deps_to_remove = {_normalise(d) for d in addon_cfg.deps}
    dev_deps_to_remove = {_normalise(d) for d in addon_cfg.dev_deps}

    removed: list[str] = []
    removed_dev: list[str] = []

    project_deps = doc.get("project", {}).get("dependencies", [])
    if isinstance(project_deps, Array):
        to_remove = []
        for d in project_deps:
            if _normalise(str(d)) in deps_to_remove:
                removed.append(str(d))
            else:
                to_remove.append(d)
        if removed:
            del project_deps[:]
            for d in to_remove:
                project_deps.append(d)

    _dev_doc = doc.get("dependency-groups", {})
    _dev_group = _dev_doc.get("dev") if hasattr(_dev_doc, "get") else None
    dev_group = _dev_group or doc.get("project", {}).get(
        "optional-dependencies", {}
    ).get("dev")
    if isinstance(dev_group, (list, Array)):
        new_dev = []
        for d in dev_group:
            if _normalise(str(d)) in dev_deps_to_remove:
                removed_dev.append(str(d))
            else:
                new_dev.append(d)
        if removed_dev:
            dep_groups = doc.get("dependency-groups")
            if isinstance(dep_groups, Mapping) and "dev" in dep_groups:
                doc["dependency-groups"]["dev"] = new_dev  # type: ignore[index]
            else:
                doc["project"]["optional-dependencies"]["dev"] = new_dev  # type: ignore[index]

    if removed or removed_dev:
        pyproject_path.write_text(tomlkit.dumps(doc), encoding="utf-8")

    return removed, removed_dev


def _remove_just_recipes(
    project_dir: Path,
    addon_cfg: AddonConfig,
    render_vars: dict[str, object],
) -> list[str]:
    """Remove just recipes contributed by this addon from the justfile."""

    justfile_path = project_dir / "justfile"
    if not justfile_path.exists() or not addon_cfg.just_recipes:
        return []

    string_env = make_env()
    recipe_names: set[str] = set()
    for raw in addon_cfg.just_recipes:
        rendered = string_env.from_string(raw).render(**render_vars)
        # Use the same regex as apply.py for consistent name extraction
        for line in rendered.splitlines():
            m = _RECIPE_NAME_RE.search(line)
            if m:
                recipe_names.add(m.group(1))

    if not recipe_names:
        return []

    text = justfile_path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    new_lines: list[str] = []
    skip = False

    for line in lines:
        stripped = line.rstrip()
        is_recipe_header = (
            stripped
            and not stripped.startswith(" ")
            and not stripped.startswith("\t")
            and not stripped.startswith("#")
        )
        if is_recipe_header:
            m = _RECIPE_NAME_RE.search(stripped)
            name = m.group(1) if m else ""
            skip = name in recipe_names
        if not skip:
            new_lines.append(line)

    justfile_path.write_text("".join(new_lines), encoding="utf-8")
    return list(recipe_names)


def _dry_remove(
    project_dir: Path,
    addon_id: str,
    addon_cfg: AddonConfig,
    lockfile: ZenitLockfile,
    pkg_name: str,
) -> None:
    """Print what `zenit remove` would do without writing anything."""

    dry_run_banner("remove", addon_id)

    dry_header("Files that would be removed")
    all_dests = {resolve_dest_placeholder(fc.dest, pkg_name) for fc in addon_cfg.files}
    for fc in addon_cfg.files:
        dest = resolve_dest_placeholder(fc.dest, pkg_name)
        full = project_dir / dest
        if dest.endswith("__init__.py") and fc.content == "":
            parent = full.parent
            siblings_on_disk = (
                {
                    p.relative_to(project_dir).as_posix()
                    for p in parent.iterdir()
                    if p.is_file() and p != full
                }
                if parent.exists()
                else set()
            )
            if siblings_on_disk - all_dests:
                continue
        if full.exists():
            print(f"  {RED}-{RESET} {dest}")
        else:
            print(f"  {DIM}  {dest}  (already missing){RESET}")

    if addon_cfg.compose_services:
        bullet_list("Compose services that would be removed:", [svc.name for svc in addon_cfg.compose_services], bullet="-", bullet_color=RED)

    if addon_cfg.env_vars:
        bullet_list("Env vars that would be removed:", [ev.key for ev in addon_cfg.env_vars], bullet="-", bullet_color=RED)

    if addon_cfg.deps or addon_cfg.dev_deps:
        bullet_list("Dependencies that would be removed from pyproject.toml:", addon_cfg.deps, bullet="-", bullet_color=RED)
        if addon_cfg.dev_deps:
            bullet_list("", addon_cfg.dev_deps, bullet="-", bullet_color=RED, suffix="(dev)")

    print()


def remove_addon_interactive(dry_run: bool = False) -> None:
    """Interactive TUI for removing a single addon from an existing project."""

    project_dir = Path.cwd()
    lockfile = read_lockfile(project_dir)

    if lockfile is None:
        error(
            "No .zenit.toml found. 'zenit remove' only works in projects scaffolded by zenit."
        )
        raise typer.Exit(1)

    if not lockfile.addons:
        error("No addons are installed in this project.")
        raise typer.Exit(1)

    available = get_available_addons()
    installed = [cfg for cfg in available if cfg.id in lockfile.addons]

    addon_id = prompt_single_addon(
        [(cfg.id, cfg.description, cfg.requires) for cfg in installed]
    )
    if addon_id is None:
        raise typer.Exit(0)

    try:
        remove_addon(addon_id, dry_run=dry_run, project_dir=project_dir)
    except ZenitError as exc:
        error(str(exc))
        raise typer.Exit(1) from exc
