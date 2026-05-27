"""Project scaffold pipeline — called by the CLI layer."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import typer

from zenit.addons._registry import get_addon, list_addons
from zenit.cli.prompt import prompt_addons, prompt_template
from zenit.cli.ui import confirm, error, info, print_commands_from_just, success
from zenit.config.config import load_config
from zenit.core._apply_loader import load_apply
from zenit.core._paths import get_zenit_root
from zenit.core.apply import apply_contributions
from zenit.core.collect import collect_all
from zenit.core.constants import _RECIPE_NAME_RE
from zenit.core.context import Context
from zenit.core.dryrun import run_dry
from zenit.core.filesystem import RealFileSystem
from zenit.core.generate import generate_all
from zenit.core.git import init
from zenit.core.lockfile import write_lockfile
from zenit.core.manifest import (
    add_compose_service,
    add_compose_volume,
    add_dependency,
    add_env_entry,
    add_just_recipe,
    dep_package_name,
    read_manifest,
    record_addon_manifest_entries,
    write_manifest,
)
from zenit.core.pkg_name import normalise_pkg_name
from zenit.core.render import build_render_vars, make_env
from zenit.core.rollback import scaffold_or_rollback
from zenit.core.validate import (
    check_preflight,
    validate_addon_deps,
    validate_name,
    validate_template_requires_addons,
)
from zenit.schema.models import EntrySource, TemplateConfig
from zenit.templates._load_config import list_templates, load_template_config


def validate_template_exists(template: str) -> None:
    """Exit with code 1 if template is not in the available templates list."""
    templates = [(t.id, t.description) for t in list_templates()]
    valid = {name for name, _ in templates}
    if template not in valid:
        error(f"Unknown template '{template}'.")
        available = "\n    ".join(f"• {name}" for name, _ in templates)
        print(f"\n  Available templates:\n    {available}\n")
        raise typer.Exit(1)


def validate_addons_exist(addons: list[str]) -> None:
    """Exit with code 1 if any addon doesn't exist."""
    available_meta = list_addons()
    available_ids = {m.id for m in available_meta}
    for addon in addons:
        if addon not in available_ids:
            error(f"Unknown addon '{addon}'.")
            valid = "\n    ".join(
                f"• {m.id}  — {m.description}" for m in available_meta
            )
            print(f"\n  Available addons:\n    {valid}\n")
            raise typer.Exit(1)


def _warn_if_nested() -> None:
    """Print a warning if cwd is inside an existing zenit project."""
    cwd = Path.cwd()
    for parent in cwd.parents:
        if (parent / ".zenit.toml").exists():
            info(
                f"You are inside an existing zenit project '{parent.name}'. "
                f"Did you mean to create a sub-project?"
            )
            break


def scaffold_project(
    name: str,
    dry_run: bool = False,
    template: str | None = None,
    addons: list[str] | None = None,
) -> None:
    """Core scaffold pipeline — called by the main CLI command."""

    zenit_root = get_zenit_root()
    pkg_name = normalise_pkg_name(name)

    _warn_if_nested()
    validate_name(name, pkg_name)

    if not dry_run:
        check_preflight()

    # Validate explicit arguments before any prompts
    if template is not None:
        validate_template_exists(template)
    if addons is not None:
        validate_addons_exist(addons)

    cfg = load_config()

    if template is not None:
        tpl = template
    else:
        tpl = prompt_template(default=cfg.default_template)

    available_meta = list_addons()
    if addons is not None:
        adns = addons
    else:
        adns = prompt_addons(available_meta, tpl, default_addons=cfg.default_addons)
    validate_addon_deps(adns, available_meta, template=tpl)

    ctx = Context(
        name=name,
        pkg_name=pkg_name,
        template=tpl,
        addons=adns,
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
    fs = RealFileSystem(project_dir)
    with scaffold_or_rollback(project_dir):
        project_dir.mkdir()

        load_apply(zenit_root / "templates" / "_common" / "apply.py")(ctx, fs)

        template_config = load_template_config(zenit_root, tpl)
        validate_template_requires_addons(template_config, adns)
        selected_addon_configs = [get_addon(a) for a in adns]

        contributions = collect_all(template_config, selected_addon_configs)

        python_version = f"{sys.version_info.major}.{sys.version_info.minor}"
        render_vars = build_render_vars(
            name=name,
            pkg_name=pkg_name,
            template=tpl,
            addons=adns,
            deps=contributions.deps,
            dev_deps=contributions.template_dev_deps + contributions.dev_deps,
            python_version=python_version,
        )

        write_lockfile(project_dir, tpl, adns)

        apply_contributions(
            ctx,
            fs,
            contributions,
            template_config.injection_points,
            render_vars,
        )
        generate_all(ctx, fs, contributions, python_version=python_version)

        manifest = read_manifest(project_dir)
        string_env = make_env()
        for addon_cfg in selected_addon_configs:
            record_addon_manifest_entries(
                manifest,
                addon_cfg,
                string_env,
                render_vars,
            )
        write_manifest(project_dir, manifest)

        _stamp_template_manifest(project_dir, template_config)

        init(project_dir)

    print()
    addon_suffix = (" + " + ", ".join(adns)) if adns else ""
    success(f"Project '{name}' ready!  ({tpl}{addon_suffix})")
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

    if "github-actions" in adns:
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
        pkg = dep_package_name(dep)
        add_dependency(
            manifest, pkg, dep, source=EntrySource.TEMPLATE, addon="", dev=False
        )

    for dep in template_config.dev_deps:
        pkg = dep_package_name(dep)
        add_dependency(
            manifest, pkg, dep, source=EntrySource.TEMPLATE, addon="", dev=True
        )

    for recipe_raw in template_config.just_recipes:
        m = _RECIPE_NAME_RE.search(recipe_raw)
        if m:
            add_just_recipe(manifest, m.group(1), source=EntrySource.TEMPLATE, addon="")

    write_manifest(project_dir, manifest)
