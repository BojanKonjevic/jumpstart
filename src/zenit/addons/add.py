"""Add‑on pipeline — apply a single addon to an existing project."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import typer

from zenit.addons._registry import get_available_addons
from zenit.addons.checks import check_can_add
from zenit.cli.prompt import prompt_multi_addon
from zenit.cli.ui import (
    DIM,
    GREEN,
    RESET,
    addon_summary,
    bullet_list,
    dry_dep,
    dry_file,
    dry_header,
    dry_run_banner,
    error,
    info,
    success,
    warn,
)
from zenit.core._paths import get_zenit_root
from zenit.core.apply import apply_contributions, merge_compose
from zenit.core.collect import collect_addon_only, collect_all
from zenit.core.context import Context
from zenit.core.deps import inject_deps
from zenit.core.filesystem import FileSystem, RealFileSystem, RecordingFileSystem
from zenit.core.justfile import inject_just_recipes
from zenit.core.lockfile import read_lockfile, write_lockfile
from zenit.core.manifest import (
    add_compose_service,
    add_compose_volume,
    read_manifest,
    record_addon_manifest_entries,
    write_manifest,
)
from zenit.core.pkg_name import normalise_pkg_name
from zenit.core.recipes import _recipe_name
from zenit.core.render import build_recipe_render_vars, build_render_vars, make_env
from zenit.core.rollback import addon_or_rollback
from zenit.schema.exceptions import ZenitError
from zenit.schema.models import AddonConfig, EntrySource
from zenit.templates._load_config import load_template_config


@dataclass
class _AddResult:
    """Result of running the add-on pipeline."""

    added_deps: list[str] = field(default_factory=list)
    added_dev_deps: list[str] = field(default_factory=list)
    added_recipes: list[str] = field(default_factory=list)
    recorded_files: list[tuple[str, str, str]] = field(default_factory=list)


def _run_add_pipeline(
    ctx: Context,
    fs: FileSystem,
    addon_id: str,
    available: list[AddonConfig],
) -> _AddResult:
    """Shared pipeline body for both real and dry-run add operations."""

    zenit_root = ctx.zenit_root
    template = ctx.template
    pkg_name = ctx.pkg_name
    project_dir = ctx.project_dir

    template_config = load_template_config(zenit_root, template)
    selected_addon_configs = [a for a in available if a.id == addon_id]
    contributions = collect_addon_only(selected_addon_configs)

    render_vars = build_render_vars(
        name=ctx.name,
        pkg_name=pkg_name,
        template=template,
        addons=ctx.addons,
    )

    apply_contributions(
        ctx,
        fs,
        contributions,
        template_config.injection_points,
        render_vars,
    )

    # ── Dependencies ──────────────────────────────────────────────────────────
    if ctx.dry_run:
        added_deps = list(contributions.deps)
        added_dev_deps = list(contributions.dev_deps)
    else:
        try:
            added_deps, added_dev_deps = inject_deps(
                project_dir,
                contributions.deps,
                contributions.dev_deps,
            )
        except FileNotFoundError as exc:
            warn(str(exc))
            added_deps, added_dev_deps = [], []

    # ── Just recipes ──────────────────────────────────────────────────────────
    recipe_render_vars = build_recipe_render_vars(
        name=ctx.name,
        pkg_name=pkg_name,
        template=template,
        addons=ctx.addons,
    )
    string_env = make_env()
    rendered_recipes = [
        string_env.from_string(r).render(**recipe_render_vars)
        for r in contributions.recipes.addon
    ]

    if ctx.dry_run:
        added_recipes = [n for r in rendered_recipes if (n := _recipe_name(r))]
    else:
        added_recipes = inject_just_recipes(project_dir, rendered_recipes)

    # ── Manifest recording ────────────────────────────────────────────────────
    if not ctx.dry_run:
        manifest = read_manifest(project_dir)
        docker_active = "docker" in ctx.addons
        for addon_cfg in selected_addon_configs:
            record_addon_manifest_entries(
                manifest,
                addon_cfg,
                string_env,
                render_vars,
                docker_active=docker_active,
            )
        write_manifest(project_dir, manifest)

    # ── Recorded files (dry-run only) ─────────────────────────────────────────
    recorded_files = list(fs.recorded_files) if ctx.dry_run else []  # type: ignore[attr-defined]

    return _AddResult(
        added_deps=added_deps,
        added_dev_deps=added_dev_deps,
        added_recipes=added_recipes,
        recorded_files=recorded_files,
    )


def add_addon(addon_id: str, dry_run: bool = False, yes: bool = False) -> None:
    """Apply a single addon to an existing zenit project."""

    project_dir = Path.cwd()
    available = get_available_addons()

    try:
        lockfile = check_can_add(project_dir, addon_id, available)
    except ZenitError as exc:
        error(str(exc))
        raise typer.Exit(1) from exc

    template = lockfile.template
    pkg_name = normalise_pkg_name(project_dir.name)
    zenit_root = get_zenit_root()

    # ── Dry-run path ──────────────────────────────────────────────────────────
    fs: FileSystem
    if dry_run:
        fs = RecordingFileSystem(project_dir)
        ctx = Context(
            name=project_dir.name,
            pkg_name=pkg_name,
            template=template,
            addons=lockfile.addons + [addon_id],
            zenit_root=zenit_root,
            project_dir=project_dir,
            dry_run=True,
        )
        result = _run_add_pipeline(ctx, fs, addon_id, available)

        dry_run_banner("add", addon_id)

        dry_header("Files that would be created or modified")
        for action, path, details in result.recorded_files:
            dry_file(path, note=details, action=action)

        if result.added_deps or result.added_dev_deps:
            dry_header("Dependencies that would be added to pyproject.toml")
            for dep in result.added_deps:
                dry_dep(dep)
            for dep in result.added_dev_deps:
                dry_dep(dep, "dev")

        if result.added_recipes:
            dry_header("Just recipes that would be added")
            for name in result.added_recipes:
                dry_dep(name)

        print()
        return

    # ── Real mode: prompt ─────────────────────────────────────────────────────
    addon_summary("add", addon_id, project_dir, template)

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
            warn("Non‑interactive mode — proceeding automatically.")

    with addon_or_rollback(project_dir, addon_id):
        ctx = Context(
            name=project_dir.name,
            pkg_name=pkg_name,
            template=template,
            addons=lockfile.addons + [addon_id],
            zenit_root=zenit_root,
            project_dir=project_dir,
        )
        fs = RealFileSystem(project_dir)
        result = _run_add_pipeline(ctx, fs, addon_id, available)
        write_lockfile(project_dir, template, ctx.addons)

    # ── Backfill compose entries when adding docker ──────────────────
    if addon_id == "docker" and not dry_run:
        _backfill_compose_on_docker_add(
            project_dir=project_dir,
            template=template,
            current_addons=ctx.addons,
            zenit_root=zenit_root,
        )

    # ── Output ────────────────────────────────────────────────────────────────
    print()
    success(f"Addon '{addon_id}' added to '{project_dir.name}'.")

    if result.added_deps or result.added_dev_deps:
        bullet_list(
            "Dependencies added to pyproject.toml:",
            result.added_deps,
            bullet="+",
            bullet_color=GREEN,
        )
        if result.added_dev_deps:
            bullet_list(
                "",
                result.added_dev_deps,
                bullet="+",
                bullet_color=GREEN,
                suffix="(dev)",
            )
        info("Run 'uv sync' to install them.")
    else:
        info("No new dependencies were needed.")

    if result.added_recipes:
        bullet_list(
            "Just recipes added:", result.added_recipes, bullet="+", bullet_color=GREEN
        )

    print()


def add_addon_interactive(dry_run: bool = False, yes: bool = False) -> None:
    """Interactive TUI for adding a single addon to an existing project."""

    project_dir = Path.cwd()
    lockfile = read_lockfile(project_dir)

    if lockfile is None:
        error(
            "No .zenit.toml found. 'zenit add' only works in projects scaffolded by zenit."
        )
        raise typer.Exit(1)

    if not lockfile.template:
        error(".zenit.toml exists but has no template field — it may be corrupt.")
        raise typer.Exit(1)

    available = get_available_addons()

    already_installed = set(lockfile.addons)
    if already_installed:
        print(
            f"\n  {DIM}Already installed: {', '.join(sorted(already_installed))}{RESET}"
        )

    items = []
    unavailable_indices = set()

    for addon in available:
        if addon.id in already_installed:
            continue

        deps_met = all(req in lockfile.addons for req in addon.requires)
        items.append((addon.id, addon.description, addon.requires))

        if not deps_met:
            unavailable_indices.add(len(items) - 1)

    if not items:
        info("All available addons are already installed.")
        print()
        return

    selected = prompt_multi_addon(
        items,
        unavailable_indices=unavailable_indices,
        context="add",
        prompt="Select addon(s) to add:",
    )

    if not selected:
        info("No addon selected.")
        print()
        return

    for addon_id in selected:
        add_addon(addon_id, dry_run=dry_run, yes=yes)


def _backfill_compose_on_docker_add(
    project_dir: Path,
    template: str,
    current_addons: list[str],
    zenit_root: Path,
) -> None:
    """When docker is added to a project with existing addons, backfill their
    compose services and volumes into both compose.yml and the manifest."""
    template_config = load_template_config(zenit_root, template)
    available = get_available_addons()
    active_configs = [a for a in available if a.id in current_addons]

    contributions = collect_all(template_config, active_configs)
    if not contributions.compose_services and not contributions.compose_volumes:
        return

    compose_path = project_dir / "compose.yml"
    if not compose_path.exists():
        return

    pkg_name = normalise_pkg_name(project_dir.name)
    ctx = Context(
        name=project_dir.name,
        pkg_name=pkg_name,
        template=template,
        addons=current_addons,
        zenit_root=zenit_root,
        project_dir=project_dir,
    )
    fs = RealFileSystem(project_dir)
    merge_compose(
        ctx, fs, contributions.compose_services, contributions.compose_volumes
    )

    manifest = read_manifest(project_dir)
    for addon_cfg in active_configs:
        for svc in addon_cfg.compose_services:
            add_compose_service(
                manifest, svc.name, source=EntrySource.ADDON, addon=addon_cfg.id
            )
        for vol in addon_cfg.compose_volumes:
            add_compose_volume(
                manifest, vol, source=EntrySource.ADDON, addon=addon_cfg.id
            )
    for svc in template_config.compose_services:
        add_compose_service(manifest, svc.name, source=EntrySource.TEMPLATE, addon="")
    for vol in template_config.compose_volumes:
        add_compose_volume(manifest, vol, source=EntrySource.TEMPLATE, addon="")
    write_manifest(project_dir, manifest)
