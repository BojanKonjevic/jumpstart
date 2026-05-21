"""Project scaffold pipeline — called by the CLI layer."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import typer

from zenit.addons._registry import get_available_addons
from zenit.cli.prompt import prompt_addons, prompt_template
from zenit.cli.ui import confirm, info, print_commands_from_just, success
from zenit.config.config import load_config
from zenit.core._apply_loader import load_apply
from zenit.core._paths import get_zenit_root
from zenit.core.apply import _pkg_name, apply_contributions
from zenit.core.collect import collect_all
from zenit.core.context import Context
from zenit.core.dryrun import run_dry
from zenit.core.generate import generate_all
from zenit.core.git import init
from zenit.core.handlers.justfile_handler import _RECIPE_NAME_RE
from zenit.core.lockfile import write_lockfile
from zenit.core.manifest import (
    add_compose_service,
    add_compose_volume,
    add_dependency,
    add_env_entry,
    add_just_recipe,
    read_manifest,
    write_manifest,
)
from zenit.core.pkg_name import normalise_pkg_name
from zenit.core.render import build_render_vars
from zenit.core.rollback import scaffold_or_rollback
from zenit.core.validate import (
    check_preflight,
    validate_addon_deps,
    validate_name,
)
from zenit.schema.models import EntrySource, TemplateConfig
from zenit.templates._load_config import load_template_config


def scaffold_project(name: str, dry_run: bool = False) -> None:
    """Core scaffold pipeline — called by the main CLI command."""

    zenit_root = get_zenit_root()
    pkg_name = normalise_pkg_name(name)

    validate_name(name, pkg_name)

    if not dry_run:
        check_preflight()

    cfg = load_config()

    template = prompt_template(default=cfg.default_template)

    available = get_available_addons()
    addons = prompt_addons(available, template, default_addons=cfg.default_addons)
    validate_addon_deps(addons, available, template=template)

    ctx = Context(
        name=name,
        pkg_name=pkg_name,
        template=template,
        addons=addons,
        zenit_root=zenit_root,
        project_dir=Path.cwd() / name,
    )

    if dry_run:
        run_dry(ctx)
        return

    if not confirm(ctx):
        print("\n  \033[0;33mAborted.\033[0m\n")
        raise typer.Exit(0)

    project_dir = ctx.project_dir
    with scaffold_or_rollback(project_dir):
        project_dir.mkdir()

        load_apply(zenit_root / "templates" / "_common" / "apply.py")(ctx)

        template_config = load_template_config(zenit_root, template)
        selected_addon_configs = [a for a in available if a.id in addons]

        contributions = collect_all(template_config, selected_addon_configs)

        render_vars = build_render_vars(
            name=name,
            pkg_name=pkg_name,
            template=template,
            addons=addons,
        )

        write_lockfile(project_dir, template, addons)

        apply_contributions(
            ctx,
            contributions,
            template_config.injection_points,
            render_vars,
        )
        generate_all(ctx, template_config, contributions)
        init(project_dir)

        _stamp_template_manifest(project_dir, template_config)

    print()
    addon_suffix = (" + " + ", ".join(addons)) if addons else ""
    success(f"Project '{name}' ready!  ({template}{addon_suffix})")
    print()
    print(f"  cd {name}")

    print_commands_from_just(project_dir)

    if sys.platform == "win32":
        print()
        info("Your environment is managed by uv — no activation needed.")
        info("Every 'just' command runs through 'uv run' and syncs automatically.")
    elif not shutil.which("direnv"):
        print()
        info("direnv not detected — run 'uv sync' once to set up your environment,")
        info("or install direnv and run 'direnv allow' for auto-activation on cd.")

    if "github-actions" in addons:
        print()
        info("GitHub Actions CI is set up at .github/workflows/ci.yml")
        print(
            "    Push to GitHub and it will lint, type-check, and test automatically."
        )


def _stamp_template_manifest(
    project_dir: Path,
    template_config: TemplateConfig,
) -> None:
    """Record template-owned entries in the manifest with source='template', addon=''.

    ``apply_contributions`` writes addon entries during the scaffold run.
    This function is called once after ``write_lockfile`` to stamp all
    template-owned env vars, compose services/volumes, dependencies, and
    just recipes with the correct ownership metadata.

    The ``add_*`` helpers are idempotent — calling them on already-recorded
    entries is safe.
    """
    manifest = read_manifest(project_dir)

    for ev in template_config.env_vars:
        add_env_entry(manifest, ev.key, source=EntrySource.TEMPLATE, addon="")

    for svc in template_config.compose_services:
        add_compose_service(manifest, svc.name, source=EntrySource.TEMPLATE, addon="")

    for vol in template_config.compose_volumes:
        add_compose_volume(manifest, vol, source=EntrySource.TEMPLATE, addon="")

    for dep in template_config.deps:
        pkg = _pkg_name(dep)
        add_dependency(manifest, pkg, dep, source=EntrySource.TEMPLATE, addon="", dev=False)

    for dep in template_config.dev_deps:
        pkg = _pkg_name(dep)
        add_dependency(manifest, pkg, dep, source=EntrySource.TEMPLATE, addon="", dev=True)

    for recipe_raw in template_config.just_recipes:
        m = _RECIPE_NAME_RE.search(recipe_raw)
        if m:
            add_just_recipe(manifest, m.group(1), source=EntrySource.TEMPLATE, addon="")

    write_manifest(project_dir, manifest)
