"""Add‑on pipeline — apply a single addon to an existing project."""

import sys
from pathlib import Path

import typer

from zenit.addons._registry import get_available_addons
from zenit.addons.checks import check_can_add
from zenit.cli.prompt import prompt_single_addon
from zenit.cli.ui import (
    BOLD,
    CYAN,
    DIM,
    GREEN,
    MAGENTA,
    RESET,
    YELLOW,
    dry_dep,
    dry_header,
    error,
    info,
    success,
    warn,
)
from zenit.core._paths import get_zenit_root
from zenit.core.apply import apply_contributions
from zenit.core.collect import collect_addon_only
from zenit.core.context import Context
from zenit.core.deps import inject_deps
from zenit.core.filesystem import RecordingFileSystem
from zenit.core.generate import _recipe_name
from zenit.core.justfile import inject_just_recipes
from zenit.core.lockfile import read_lockfile, write_lockfile
from zenit.core.render import build_recipe_render_vars, build_render_vars, make_env
from zenit.core.rollback import addon_or_rollback
from zenit.schema.exceptions import ZenitError
from zenit.schema.models import AddonConfig
from zenit.templates._load_config import load_template_config


def add_addon(addon_id: str, dry_run: bool = False) -> None:
    """Apply a single addon to an existing zenit project."""

    project_dir = Path.cwd()
    available = get_available_addons()

    try:
        lockfile = check_can_add(project_dir, addon_id, available)
    except ZenitError as exc:
        error(str(exc))
        raise typer.Exit(1) from exc

    template = lockfile.template
    pkg_name = project_dir.name.replace("-", "_")
    zenit_root = get_zenit_root()

    ctx = Context(
        name=project_dir.name,
        pkg_name=pkg_name,
        template=template,
        addons=lockfile.addons + [addon_id],
        zenit_root=zenit_root,
        project_dir=project_dir,
    )

    if dry_run:
        _dry_add(ctx, addon_id, available, template)
        return

    print(f"\n  {BOLD}Ready to add addon:{RESET}")
    print(f"\n    {'addon':<12}  {BOLD}{addon_id}{RESET}")
    print(f"    {'project':<12}  {DIM}{project_dir}{RESET}")
    print(f"    {'template':<12}  {CYAN}{template}{RESET}")
    print()

    if sys.stdin.isatty():
        try:
            raw = input(f"  Proceed? {DIM}[Y/n]{RESET}  ").strip().lower()
        except EOFError, KeyboardInterrupt:
            print()
            raise typer.Exit(0) from None
        if raw not in ("", "y", "yes"):
            print(f"\n  {YELLOW}Aborted.{RESET}\n")
            raise typer.Exit(0)
    else:
        warn("Non‑interactive mode — proceeding automatically.")

    with addon_or_rollback(project_dir, addon_id):
        template_config = load_template_config(zenit_root, template)
        selected_addon_configs = [a for a in available if a.id == addon_id]

        render_vars = build_render_vars(
            name=project_dir.name,
            pkg_name=pkg_name,
            template=template,
            has_postgres=template == "fastapi",
            has_redis="redis" in ctx.addons,
        )

        contributions = collect_addon_only(selected_addon_configs)

        apply_contributions(
            ctx,
            contributions,
            template_config.injection_points,
            render_vars,
        )

        try:
            added_deps, added_dev_deps = inject_deps(
                project_dir,
                contributions.deps,
                contributions.dev_deps,
            )
        except FileNotFoundError as exc:
            warn(str(exc))
            added_deps, added_dev_deps = [], []

        recipe_render_vars = build_recipe_render_vars(
            name=project_dir.name,
            pkg_name=pkg_name,
            template=template,
            addons=ctx.addons,
        )
        string_env = make_env()
        rendered_recipes = [
            string_env.from_string(r).render(**recipe_render_vars)
            for r in contributions.just_recipes
        ]
        added_recipes = inject_just_recipes(project_dir, rendered_recipes)

        new_addons = lockfile.addons + [addon_id]
        write_lockfile(project_dir, template, new_addons)

    # ── output ────────────────────────────────────────────────────────────
    print()
    success(f"Addon '{addon_id}' added to '{project_dir.name}'.")

    if added_deps or added_dev_deps:
        print()
        print(f"  {BOLD}Dependencies added to pyproject.toml:{RESET}")
        for dep in added_deps:
            print(f"    {GREEN}+{RESET} {dep}")
        for dep in added_dev_deps:
            print(f"    {GREEN}+{RESET} {dep}  {DIM}(dev){RESET}")
        info("Run 'uv sync' to install them.")
    else:
        info("No new dependencies were needed.")

    if added_recipes:
        print()
        print(f"  {BOLD}Just recipes added:{RESET}")
        for name in added_recipes:
            print(f"    {GREEN}+{RESET} {name}")

    print()


def _dry_add(
    ctx: Context,
    addon_id: str,
    available: list[AddonConfig],
    template: str,
) -> None:
    """Print what `zenit add` would do without writing anything."""

    zenit_root = ctx.zenit_root
    fs = RecordingFileSystem(ctx.project_dir)
    dry_ctx = Context(
        name=ctx.name,
        pkg_name=ctx.pkg_name,
        template=template,
        addons=ctx.addons,
        zenit_root=zenit_root,
        project_dir=ctx.project_dir,
        _fs=fs,
    )

    template_config = load_template_config(zenit_root, template)
    selected_addon_configs = [a for a in available if a.id == addon_id]
    contributions = collect_addon_only(selected_addon_configs)

    render_vars = build_render_vars(
        name=ctx.name,
        pkg_name=ctx.pkg_name,
        template=template,
        has_postgres=template == "fastapi",
        has_redis="redis" in ctx.addons,
    )

    apply_contributions(
        dry_ctx,
        contributions,
        template_config.injection_points,
        render_vars,
    )

    print(
        f"\n  {BOLD}{MAGENTA}Dry run:{RESET} zenit add {addon_id}"
        f"  {DIM}(nothing will be written){RESET}\n"
    )

    dry_header("Files that would be created or modified")
    for action, path, details in fs.recorded_files:
        if action in ("create", "copy"):
            print(f"  {GREEN}+{RESET} {path}")
        elif action == "append":
            print(f"  {GREEN}+{RESET} {path}  {DIM}(appended){RESET}")
        elif action == "modify":
            print(f"  {GREEN}△{RESET} {path}  {DIM}{details}{RESET}")

    if contributions.deps or contributions.dev_deps:
        dry_header("Dependencies that would be added to pyproject.toml")
        for dep in contributions.deps:
            dry_dep(dep)
        for dep in contributions.dev_deps:
            dry_dep(dep, "dev")

    if contributions.just_recipes:
        dry_header("Just recipes that would be added")
        recipe_render_vars = build_recipe_render_vars(
            name=ctx.name,
            pkg_name=ctx.pkg_name,
            template=template,
            addons=ctx.addons,
        )
        string_env = make_env()
        for recipe in contributions.just_recipes:
            rendered = string_env.from_string(recipe).render(**recipe_render_vars)
            name = _recipe_name(rendered)
            if name:
                dry_dep(name)

    print()


def add_addon_interactive(dry_run: bool = False) -> None:
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

    selected = prompt_single_addon(
        items,
        unavailable_indices=unavailable_indices,
    )

    if not selected:
        info("No addon selected.")
        print()
        return

    add_addon(selected, dry_run=dry_run)
