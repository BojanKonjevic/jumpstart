"""Add‑on pipeline — apply a single addon to an existing project."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import typer

from zenit.addons._registry import get_addon, list_addons
from zenit.addons.checks import check_can_add
from zenit.cli.prompt import prompt_multi_addon
from zenit.cli.ui import (
    DIM,
    GREEN,
    RESET,
    abort,
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
from zenit.core.apply import apply_contributions
from zenit.core.collect import collect_addon_only
from zenit.core.constants import _recipe_name
from zenit.core.context import Context
from zenit.core.dependency import DependencyGraph
from zenit.core.deps import inject_deps
from zenit.core.filesystem import FileSystem, RealFileSystem, RecordingFileSystem
from zenit.core.justfile import inject_just_recipes
from zenit.core.lockfile import read_lockfile, write_lockfile
from zenit.core.manifest import (
    read_manifest,
    record_addon_manifest_entries,
    write_manifest,
)
from zenit.core.pkg_name import normalise_pkg_name
from zenit.core.render import build_recipe_render_vars, build_render_vars, make_env
from zenit.core.rollback import addon_or_rollback
from zenit.schema.exceptions import ZenitError
from zenit.schema.models import AddonConfig
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
    addon_cfg: AddonConfig,
) -> _AddResult:
    """Shared pipeline body for both real and dry-run add operations."""

    zenit_root = ctx.zenit_root
    template = ctx.template
    pkg_name = ctx.pkg_name
    project_dir = ctx.project_dir

    template_config = load_template_config(zenit_root, template)
    contributions = collect_addon_only([addon_cfg])

    render_vars = build_render_vars(
        name=ctx.name,
        pkg_name=pkg_name,
        template=template,
        addons=ctx.addons,
        deps=contributions.deps,
        dev_deps=contributions.dev_deps,
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
        deps=contributions.deps,
        dev_deps=contributions.dev_deps,
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
        record_addon_manifest_entries(
            manifest,
            addon_cfg,
            string_env,
            render_vars,
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


def add_addon(
    addon_id: str,
    dry_run: bool = False,
    yes: bool = False,
    project_dir: Path | None = None,
) -> None:
    """Apply a single addon to an existing zenit project."""

    if project_dir is None:
        project_dir = Path.cwd()

    try:
        lockfile = check_can_add(project_dir, addon_id)
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
        addon_cfg = get_addon(addon_id)
        result = _run_add_pipeline(ctx, fs, addon_cfg)

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
            abort()
        if raw not in ("", "y", "yes"):
            warn("Aborted.")
            raise typer.Exit(0)
    else:
        if yes:
            pass
        else:
            warn("Non‑interactive mode — proceeding automatically.")

    addon_cfg = get_addon(addon_id)
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
        result = _run_add_pipeline(ctx, fs, addon_cfg)
        write_lockfile(project_dir, template, ctx.addons)

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


def add_addon_interactive(
    dry_run: bool = False, yes: bool = False, project_dir: Path | None = None
) -> None:
    """Interactive TUI for adding a single addon to an existing project."""

    if project_dir is None:
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

    available_meta = list_addons()
    graph = DependencyGraph.build_from_meta(available_meta)

    already_installed = set(lockfile.addons)
    if already_installed:
        print(
            f"\n  {DIM}Already installed: {', '.join(sorted(already_installed))}{RESET}"
        )

    requires_map = {m.id: m.requires for m in available_meta}
    items = []

    for addon_meta in available_meta:
        if addon_meta.id in already_installed:
            continue

        items.append((addon_meta.id, addon_meta.description, addon_meta.requires))

    if not items:
        info("All available addons are already installed.")
        print()
        return

    selected = prompt_multi_addon(
        items,
        context="add",
        prompt="Select addon(s) to add:",
        requires_map=requires_map,
    )

    if not selected:
        info("No addon selected.")
        print()
        return

    for addon_id in graph.tsort(set(selected)):
        add_addon(addon_id, dry_run=dry_run, yes=yes)
