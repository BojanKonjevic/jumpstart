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
from zenit.cli.prompt import prompt_multi_addon
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
from zenit.core._paths import get_zenit_root
from zenit.core.handlers import HandlerDispatcher
from zenit.core.handlers.justfile_handler import _RECIPE_NAME_RE
from zenit.core.lockfile import ZenitLockfile, read_lockfile, write_lockfile
from zenit.core.manifest import (
    fingerprint as _fingerprint,
)
from zenit.core.manifest import (
    read_manifest,
    remove_blocks_for_addon,
    write_manifest,
)
from zenit.core.pkg_name import normalise_pkg_name, resolve_dest_placeholder
from zenit.schema.exceptions import ZenitError
from zenit.schema.models import AddonConfig, Manifest
from zenit.templates._load_config import load_template_config


def _check_fuzzy_blocks(
    manifest: Manifest,
    addon_id: str,
    project_dir: Path,
) -> list[tuple[str, str, str]]:
    """Return list of ``(file, point, lines)`` for blocks that would hit fuzzy removal.

    For each Python block belonging to *addon_id*, reads the current file at
    the recorded line range and compares fingerprints.  Blocks where neither
    the exact fingerprint (Stage A) nor the normalised fingerprint (Stage B)
    match are returned — these would fall through to Stage C (fuzzy) removal.
    """
    result: list[tuple[str, str, str]] = []
    for block in manifest.python_blocks:
        if block.addon != addon_id:
            continue
        file_path = project_dir / block.file
        if not file_path.exists():
            continue
        source = file_path.read_text(encoding="utf-8")
        lines = source.splitlines(keepends=True)

        start_str, end_str = block.lines.split("-")
        rec_start = int(start_str) - 1
        rec_end = int(end_str) - 1

        if rec_start < 0 or rec_end >= len(lines):
            continue

        candidate = "".join(lines[rec_start : rec_end + 1])
        fp, fp_norm = _fingerprint(candidate)

        if fp == block.fingerprint or fp_norm == block.fingerprint_normalised:
            continue

        result.append((block.file, block.point, block.lines))
    return result


def remove_addon(
    addon_id: str,
    dry_run: bool = False,
    yes: bool = False,
    project_dir: Path | None = None,
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

    # ── read manifest once, before any prompts or removals ──────────────────
    manifest = read_manifest(project_dir)

    # ── fuzzy-block check ─────────────────────────────────────────────────
    fuzzy_blocks = _check_fuzzy_blocks(manifest, addon_id, project_dir)
    if fuzzy_blocks:
        warn("Some injected code has been modified since it was added:")
        for file, point, lines in fuzzy_blocks:
            warn(f"  {file}:{point}  (lines {lines})")
        print()

        if yes:
            error(
                "Re-run without --yes to interactively confirm fuzzy removal, "
                "or inspect the modified files and remove the injected code manually."
            )
            raise typer.Exit(1)

        if sys.stdin.isatty():
            try:
                raw = (
                    input(f"  Use fuzzy matching to remove it? {DIM}[y/N]{RESET}  ")
                    .strip()
                    .lower()
                )
            except (EOFError, KeyboardInterrupt):
                print()
                raise typer.Exit(0) from None
            if raw not in ("y", "yes"):
                warn("Aborted.")
                raise typer.Exit(0)
        else:
            warn("Non-interactive mode — proceeding automatically.")

    if sys.stdin.isatty() and not yes:
        try:
            raw = input(f"  Proceed? {DIM}[Y/n]{RESET}  ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            raise typer.Exit(0) from None
        if raw not in ("", "y", "yes"):
            warn("Aborted.")
            raise typer.Exit(0)
    else:
        if yes:
            pass
        else:
            warn("Non-interactive mode — proceeding automatically.")

    # ── files ──────────────────────────────────────────────────────────────
    removed_files = _remove_files(project_dir, addon_cfg, pkg_name)

    # ── injections (physical removal only — manifest written at the end) ────
    _undo_injections_physical(project_dir, manifest, addon_id)

    # ── compose services ────────────────────────────────────────────────────
    removed_services = _remove_compose_services(project_dir, manifest, addon_id)
    _remove_compose_volumes(project_dir, manifest, addon_id)

    # ── env vars ─────────────────────────────────────────────────────────────
    removed_env_vars = _remove_env_vars(project_dir, manifest, addon_id)

    # ── deps ──────────────────────────────────────────────────────────────
    removed_deps, removed_dev_deps = _remove_deps(project_dir, manifest, addon_id)

    # ── justfile recipes ──────────────────────────────────────────────────
    removed_recipes = _remove_just_recipes(project_dir, manifest, addon_id)

    # ── manifest (written once, after all physical removals succeed) ────────
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
        bullet_list(
            "Dependencies removed from pyproject.toml:",
            removed_deps,
            bullet="-",
            bullet_color=RED,
        )
        if removed_dev_deps:
            bullet_list(
                "", removed_dev_deps, bullet="-", bullet_color=RED, suffix="(dev)"
            )
        info("Run 'uv sync' to uninstall them.")

    if removed_recipes:
        bullet_list(
            "Just recipes removed:", removed_recipes, bullet="-", bullet_color=RED
        )

    if removed_services:
        bullet_list(
            "Compose services removed:", removed_services, bullet="-", bullet_color=RED
        )

    if removed_env_vars:
        bullet_list("Env vars removed:", removed_env_vars, bullet="-", bullet_color=RED)

    print()


# ── Removal helpers ───────────────────────────────────────────────────────────
# Removing a zenit-managed addon involves two categories:
#   1. Structured-entry removal — compose services/volumes, env vars, deps, and
#      just recipes are tracked as manifest entries and removed by dedicated
#      helpers (_remove_compose_services, _remove_env_vars, etc.).
#   2. Line-range removal — Python code injections are tracked as ManifestBlock
#      entries (with line ranges and fingerprints) and removed by
#      _undo_injections_physical via HandlerDispatcher.
# This separation keeps each removal path simple and explicit.


def _remove_files(
    project_dir: Path, addon_cfg: AddonConfig, pkg_name: str
) -> list[str]:
    """Delete files that were created by this addon. Returns list of removed paths."""

    removed: list[str] = []

    # Phase 1 — delete all contributed files except empty __init__.py
    for fc in addon_cfg.files:
        dest = resolve_dest_placeholder(fc.dest, pkg_name)
        if dest.endswith("__init__.py") and fc.content == "":
            continue
        full = project_dir / dest
        if full.exists():
            full.unlink()
            removed.append(dest)
            _prune_empty_parents(full.parent, project_dir)

    # Phase 2 — delete empty __init__.py only in truly empty directories
    for fc in addon_cfg.files:
        dest = resolve_dest_placeholder(fc.dest, pkg_name)
        if not (dest.endswith("__init__.py") and fc.content == ""):
            continue
        full = project_dir / dest
        if not full.exists():
            continue
        parent = full.parent
        if parent.exists() and not any(p for p in parent.iterdir() if p != full):
            full.unlink()
            removed.append(dest)
            _prune_empty_parents(parent, project_dir)

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
    manifest: Manifest,
    addon_id: str,
) -> None:
    """Physically remove all Python blocks injected by *addon_id*.

    Uses the pre-read *manifest* to find recorded blocks, dispatches each to
    the appropriate handler's remove(), and stops.  It does NOT mutate or
    write the manifest — that is the caller's responsibility, once all other
    physical removals have also succeeded.  This keeps manifest writes atomic
    with respect to the full removal sequence.
    """

    dispatcher = HandlerDispatcher()

    for block in list(manifest.python_blocks):
        if block.addon != addon_id:
            continue
        file_path = project_dir / block.file
        if not file_path.exists():
            print(
                f"Warning: '{block.file}' is missing — skipping removal of "
                f"'{block.point}' injection for addon '{addon_id}'. "
                f"Run 'zenit doctor' to verify project integrity.",
                file=sys.stderr,
            )
            continue
        dispatcher.remove(file_path, block)


def _remove_compose_services(
    project_dir: Path,
    manifest: Manifest,
    addon_id: str,
) -> list[str]:
    """Remove compose services that belong to this addon. Returns removed service names."""

    compose_path = project_dir / "compose.yml"
    if not compose_path.exists():
        return []

    data: dict[str, Any] = (
        yaml.safe_load(compose_path.read_text(encoding="utf-8")) or {}
    )
    services: dict[str, Any] = data.get("services", {})

    removed: list[str] = []
    for entry in manifest.compose_services:
        if entry.addon != addon_id:
            continue
        if entry.name in services:
            del services[entry.name]
            removed.append(entry.name)

    if removed:
        compose_path.write_text(
            yaml.dump(data, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )

    return removed


def _remove_compose_volumes(
    project_dir: Path, manifest: Manifest, addon_id: str
) -> None:
    """Remove named volumes that belong to this addon from compose.yml."""

    compose_path = project_dir / "compose.yml"
    if not compose_path.exists():
        return

    data: dict[str, Any] = (
        yaml.safe_load(compose_path.read_text(encoding="utf-8")) or {}
    )
    vols: dict[str, Any] = data.get("volumes", {})

    changed = False
    for entry in manifest.compose_volumes:
        if entry.addon != addon_id:
            continue
        if entry.name in vols:
            del vols[entry.name]
            changed = True

    if changed:
        compose_path.write_text(
            yaml.dump(data, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )


def _remove_env_vars(
    project_dir: Path,
    manifest: Manifest,
    addon_id: str,
) -> list[str]:
    """Remove env var lines owned by this addon. Returns removed keys."""

    keys_to_remove = {e.key for e in manifest.env if e.addon == addon_id}
    if not keys_to_remove:
        return []
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
    project_dir: Path, manifest: Manifest, addon_id: str
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

    deps_to_remove = {
        d.package for d in manifest.dependencies if d.addon == addon_id and not d.dev
    }
    dev_deps_to_remove = {
        d.package for d in manifest.dependencies if d.addon == addon_id and d.dev
    }

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
                doc["dependency-groups"]["dev"] = new_dev
            else:
                doc["project"]["optional-dependencies"]["dev"] = new_dev

    if removed or removed_dev:
        pyproject_path.write_text(tomlkit.dumps(doc), encoding="utf-8")

    return removed, removed_dev


def _remove_just_recipes(
    project_dir: Path,
    manifest: Manifest,
    addon_id: str,
) -> list[str]:
    """Remove just recipes contributed by this addon from the justfile."""

    justfile_path = project_dir / "justfile"
    if not justfile_path.exists():
        return []

    recipe_names = {r.name for r in manifest.just_recipes if r.addon == addon_id}
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
    # Phase 1 — show all non-empty-init files
    for fc in addon_cfg.files:
        dest = resolve_dest_placeholder(fc.dest, pkg_name)
        if dest.endswith("__init__.py") and fc.content == "":
            continue
        full = project_dir / dest
        if full.exists():
            print(f"  {RED}-{RESET} {dest}")
        else:
            print(f"  {DIM}  {dest}  (already missing){RESET}")
    # Phase 2 — show empty __init__.py only if parent would be truly empty
    all_this_addon_dests = {
        resolve_dest_placeholder(fc.dest, pkg_name) for fc in addon_cfg.files
    }
    all_this_addon_paths = {project_dir / d for d in all_this_addon_dests}
    for fc in addon_cfg.files:
        dest = resolve_dest_placeholder(fc.dest, pkg_name)
        if not (dest.endswith("__init__.py") and fc.content == ""):
            continue
        full = project_dir / dest
        parent = full.parent
        if not parent.exists():
            continue
        surviving_children = set(parent.iterdir()) - all_this_addon_paths
        if surviving_children:
            continue
        if full.exists():
            print(f"  {RED}-{RESET} {dest}")
        else:
            print(f"  {DIM}  {dest}  (already missing){RESET}")

    if addon_cfg.compose_services:
        bullet_list(
            "Compose services that would be removed:",
            [svc.name for svc in addon_cfg.compose_services],
            bullet="-",
            bullet_color=RED,
        )

    if addon_cfg.env_vars:
        bullet_list(
            "Env vars that would be removed:",
            [ev.key for ev in addon_cfg.env_vars],
            bullet="-",
            bullet_color=RED,
        )

    if addon_cfg.deps or addon_cfg.dev_deps:
        bullet_list(
            "Dependencies that would be removed from pyproject.toml:",
            addon_cfg.deps,
            bullet="-",
            bullet_color=RED,
        )
        if addon_cfg.dev_deps:
            bullet_list(
                "", addon_cfg.dev_deps, bullet="-", bullet_color=RED, suffix="(dev)"
            )

    print()


def remove_addon_interactive(dry_run: bool = False, yes: bool = False) -> None:
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

    requires_map = {cfg.id: cfg.requires for cfg in available}

    zenit_root = get_zenit_root()
    template_required: set[str] = set()
    try:
        template_config = load_template_config(zenit_root, lockfile.template)
        template_required = set(template_config.requires_addons)
    except FileNotFoundError:
        pass

    items = []
    unavailable_indices: set[int] = set()

    installed.sort(key=lambda c: c.id)

    for i, addon in enumerate(installed):
        dependents = [
            other_id
            for other_id in lockfile.addons
            if other_id != addon.id and addon.id in requires_map.get(other_id, [])
        ]
        reasons: list[str] = []
        if dependents:
            reasons.extend(dependents)
        if addon.id in template_required:
            reasons.append(f"__template__{lockfile.template}")
        items.append((addon.id, addon.description, reasons))
        if reasons:
            unavailable_indices.add(i)

    selected = prompt_multi_addon(
        items,
        unavailable_indices=unavailable_indices,
        context="remove",
        prompt="Select addon(s) to remove:",
    )

    if not selected:
        raise typer.Exit(0)

    # Process dependents before their dependencies (leaves first).
    def _dep_order(a: str) -> int:
        deps = requires_map.get(a, [])
        return -len(deps)

    for addon_id in sorted(selected, key=_dep_order):
        try:
            remove_addon(addon_id, dry_run=dry_run, yes=yes, project_dir=project_dir)
        except ZenitError as exc:
            error(str(exc))
            raise typer.Exit(1) from exc
