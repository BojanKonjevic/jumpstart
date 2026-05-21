#!/usr/bin/env python3
"""zenit — scaffold Python projects from a template with optional addons."""

from __future__ import annotations

from collections.abc import Sequence
from importlib.metadata import version as get_version
from pathlib import Path
from typing import Annotated

import typer

from zenit.addons._registry import get_available_addons
from zenit.addons.add import add_addon
from zenit.cli.prompt._render import TEMPLATES
from zenit.cli.ui import BOLD, CYAN, DIM, GREEN, RED, RESET
from zenit.config.config import config_path, load_config
from zenit.core.lockfile import read_lockfile
from zenit.core.scaffold import scaffold_project
from zenit.doctor.doctor import print_results, run_doctor
from zenit.schema.models import AddonConfig

app = typer.Typer(
    name="zenit",
    add_completion=False,
    pretty_exceptions_enable=False,
    no_args_is_help=True,
)


@app.callback()
def main_callback(
    version: Annotated[
        bool,
        typer.Option("--version", help="Show the version and exit"),
    ] = False,
) -> None:
    """Scaffold Python projects from a template with optional addons."""
    if version:
        print(get_version("zenit"))
        raise typer.Exit()


@app.command("create")
def cmd_create(
    name: Annotated[str, typer.Argument(help="Name of the project to create")],
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Preview without writing anything")
    ] = False,
) -> None:
    """Create a new project from a template."""
    scaffold_project(name, dry_run=dry_run)


@app.command("list")
def cmd_list(
    available: Annotated[
        bool,
        typer.Option(
            "--available", help="List all templates and addons Zenit knows about"
        ),
    ] = False,
    installed: Annotated[
        bool,
        typer.Option(
            "--installed", help="List what is installed in the current project"
        ),
    ] = False,
) -> None:
    """List templates and addons — available, installed, or both."""
    if available and installed:
        from zenit.cli.ui import error

        error("--available and --installed are mutually exclusive.")
        raise typer.Exit(1)

    project_dir = Path.cwd()
    lockfile = read_lockfile(project_dir)

    if installed:
        if lockfile is None:
            from zenit.cli.ui import error

            error(
                "No .zenit.toml found. "
                "'zenit list --installed' only works inside a Zenit project."
            )
            raise typer.Exit(1)
        _print_installed(lockfile, project_dir)
        return

    if available or lockfile is None:
        _print_available(TEMPLATES, get_available_addons())
        return

    _print_default(lockfile, get_available_addons(), project_dir)


def _print_available(
    templates: list[tuple[str, str]],
    addons: Sequence[AddonConfig],
) -> None:
    print(f"\n  {BOLD}Templates{RESET}")
    for name, desc in templates:
        print(f"    {CYAN}{name:<14}{RESET}  {DIM}{desc}{RESET}")

    print(f"\n  {BOLD}Addons{RESET}")
    for addon in addons:
        req_suffix = (
            f"  {DIM}requires: {', '.join(addon.requires)}{RESET}"
            if addon.requires
            else ""
        )
        tmpl_suffix = (
            f"  {DIM}({', '.join(addon.templates)} only){RESET}"
            if addon.templates
            else ""
        )
        print(
            f"    {CYAN}{addon.id:<20}{RESET}  {DIM}{addon.description}{RESET}"
            f"{req_suffix}{tmpl_suffix}"
        )
    print()


def _print_installed(
    lockfile: object,
    project_dir: Path,
) -> None:
    from zenit.core.lockfile import ZenitLockfile

    assert isinstance(lockfile, ZenitLockfile)

    version_label = lockfile.zenit_version or "unknown"
    print(f"\n  {BOLD}Project{RESET}   {project_dir.name}")
    print(f"  {BOLD}Template{RESET}  {CYAN}{lockfile.template}{RESET}")
    print(f"  {BOLD}Version{RESET}   {DIM}zenit {version_label}{RESET}")

    if lockfile.addons:
        print(f"\n  {BOLD}Installed addons{RESET}")
        for addon_id in lockfile.addons:
            print(f"    {GREEN}✓{RESET}  {addon_id}")
    else:
        print(f"\n  {DIM}No addons installed.{RESET}")
    print()


def _print_default(
    lockfile: object,
    addons: Sequence[AddonConfig],
    project_dir: Path,
) -> None:
    from zenit.core.lockfile import ZenitLockfile

    assert isinstance(lockfile, ZenitLockfile)

    version_label = lockfile.zenit_version or "unknown"
    print(f"\n  {BOLD}Project{RESET}   {project_dir.name}")
    print(f"  {BOLD}Template{RESET}  {CYAN}{lockfile.template}{RESET}")
    print(f"  {BOLD}Version{RESET}   {DIM}zenit {version_label}{RESET}")

    if lockfile.addons:
        print(f"\n  {BOLD}Installed{RESET}")
        for addon_id in lockfile.addons:
            print(f"    {GREEN}✓{RESET}  {addon_id}")
    else:
        print(f"\n  {DIM}No addons installed.{RESET}")

    installed_set = set(lockfile.addons)
    available_to_add = [
        addon
        for addon in addons
        if addon.id not in installed_set
        and (not addon.templates or lockfile.template in addon.templates)
    ]

    if available_to_add:
        print(f"\n  {BOLD}Available to add{RESET}")
        for addon in available_to_add:
            req_parts: list[str] = []
            for req in addon.requires:
                if req in installed_set:
                    req_parts.append(f"{req} {GREEN}(installed){RESET}")
                else:
                    req_parts.append(f"{RED}{req} (required){RESET}")
            req_suffix = (
                f"  {DIM}Requires: {', '.join(req_parts)}{RESET}" if req_parts else ""
            )
            print(
                f"    {CYAN}{addon.id:<20}{RESET}  {DIM}{addon.description}{RESET}"
                f"{req_suffix}"
            )
    else:
        print(f"\n  {DIM}All available addons are already installed.{RESET}")
    print()


@app.command("config")
def cmd_config() -> None:
    """Show the config file path and current settings."""
    path = config_path()
    cfg = load_config()

    print(f"\n  {BOLD}Config file:{RESET}  {CYAN}{path}{RESET}")
    if path.exists():
        print(f"  {GREEN}✓{RESET}  {DIM}file exists{RESET}")
    else:
        print(f"  {DIM}file does not exist — using built‑in defaults{RESET}")

    print()
    template_val = (
        f"{cfg.default_template}" if cfg.default_template else f"{DIM}not set{RESET}"
    )
    addons_val = (
        ", ".join(cfg.default_addons) if cfg.default_addons else f"{DIM}not set{RESET}"
    )
    print(f"  default_template  =  {template_val}")
    print(f"  default_addons    =  {addons_val}")

    if not path.exists():
        print()
        print(f"  {DIM}Create the file to set your own defaults.  Example:{RESET}")
        print()
        print(f'  {DIM}  default_template = "fastapi"{RESET}')
        print(f'  {DIM}  default_addons = ["docker", "github-actions"]{RESET}')

    print()


@app.command("add")
def cmd_add(
    addon: Annotated[
        str | None,
        typer.Argument(
            help="Addon to add to the current project (omit for interactive selection)"
        ),
    ] = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Preview without writing anything")
    ] = False,
) -> None:
    """Add an addon to an existing zenit project in the current directory.

    Run without arguments to select addons interactively.
    """
    if addon is None:
        from zenit.addons.add import add_addon_interactive

        add_addon_interactive(dry_run=dry_run)
    else:
        add_addon(addon, dry_run=dry_run)


@app.command("remove")
def cmd_remove(
    addon: Annotated[
        str | None,
        typer.Argument(
            help="Addon to remove from the current project (omit for interactive selection)"
        ),
    ] = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Preview without writing anything")
    ] = False,
) -> None:
    """Remove an addon from an existing zenit project in the current directory.

    Run without arguments to select an addon interactively.
    """
    if addon is None:
        from zenit.addons.remove import remove_addon_interactive

        remove_addon_interactive(dry_run=dry_run)
    else:
        from zenit.addons.remove import remove_addon
        from zenit.schema.exceptions import ZenitError

        try:
            remove_addon(addon, dry_run=dry_run)
        except ZenitError as exc:
            from zenit.cli.ui import error

            error(str(exc))
            raise typer.Exit(1) from exc


@app.command("doctor")
def cmd_doctor(
    thorough: Annotated[
        bool,
        typer.Option(
            "--thorough", help="Run full Python block integrity checks (slower)"
        ),
    ] = False,
) -> None:
    """Check that the current project matches zenit's expectations."""
    project_dir = Path.cwd()
    lockfile = read_lockfile(project_dir)

    if lockfile is None:
        from zenit.cli.ui import error

        error(
            "No .zenit.toml found. 'zenit doctor' only works in projects scaffolded by zenit."
        )
        raise typer.Exit(1)

    print(f"\n  Checking project '{project_dir.name}'…")
    if thorough:
        print(f"  {DIM}Thorough mode — parsing Python files with libcst.{RESET}")

    results = run_doctor(project_dir, thorough=thorough)

    if not results:
        print("\n  No checks registered yet.\n")
        return

    has_errors = print_results(results)

    print()
    if has_errors:
        from zenit.cli.ui import error

        error("Project has issues that may prevent zenit commands from working.")
        raise typer.Exit(1)
    else:
        from zenit.cli.ui import success

        success("Project looks healthy.")
    print()


def main() -> None:
    app()


if __name__ == "__main__":
    main()
