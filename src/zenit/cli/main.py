#!/usr/bin/env python3
"""zenit — scaffold Python projects from a template with optional addons."""

from __future__ import annotations

from collections.abc import Sequence
from importlib.metadata import version as get_version
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

if TYPE_CHECKING:
    from zenit.core.lockfile import ZenitLockfile
    from zenit.schema.models import AddonMeta

import typer

from zenit.cli.ui import BOLD, CYAN, DIM, GREEN, RED, RESET


def _parse_addon_list(raw: list[str] | None) -> list[str] | None:
    """Parse addon list from CLI arg — handles repeated ``-a`` and comma-separated values.

    Each argument is split by commas, then flattened and stripped.
    Duplicates are removed while preserving insertion order.
    """
    if raw is None:
        return None
    seen: set[str] = set()
    result: list[str] = []
    for item in raw:
        for p in (p.strip() for p in item.split(",") if p.strip()):
            if p not in seen:
                seen.add(p)
                result.append(p)
    return result if result else None


def _parse_data_flags(raw: list[str]) -> dict[str, str]:
    """Parse ``-D key=value`` flags into a dict.

    Each flag must contain exactly one ``=`` sign.
    """
    result: dict[str, str] = {}
    for item in raw:
        if "=" not in item:
            raise typer.BadParameter(
                f"Invalid --data value {item!r}: expected key=value format"
            )
        key, value = item.split("=", 1)
        result[key.strip()] = value.strip()
    return result


app = typer.Typer(
    name="zenit",
    add_completion=False,
    pretty_exceptions_enable=False,
)


@app.callback(invoke_without_command=True)
def main_callback(
    ctx: typer.Context,
    version: Annotated[
        bool,
        typer.Option("--version", help="Show the version and exit"),
    ] = False,
) -> None:
    """Scaffold Python projects from a template with optional addons."""
    if version:
        print(get_version("zenit"))
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        print(ctx.get_help())
        raise typer.Exit()


@app.command("create")
def cmd_create(
    name: Annotated[str, typer.Argument(help="Name of the project to create")],
    template: Annotated[
        str | None,
        typer.Option(
            "--template",
            "-t",
            help="Template to use (skip interactive picker)",
        ),
    ] = None,
    addons: Annotated[
        list[str] | None,
        typer.Option(
            "--addons",
            "-a",
            help="Addon(s) to include (repeat flag or comma-separated, e.g. -a redis,celery)",
        ),
    ] = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Preview without writing anything")
    ] = False,
) -> None:
    """Create a new project from a template."""
    from zenit.core.scaffold import scaffold_project

    parsed_addons = _parse_addon_list(addons)
    scaffold_project(name, dry_run=dry_run, template=template, addons=parsed_addons)


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

    from zenit.addons._registry import list_addons
    from zenit.core.lockfile import read_lockfile
    from zenit.templates._load_config import list_templates

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

    templates_list = [(t.id, t.description) for t in list_templates()]
    if available or lockfile is None:
        _print_available(templates_list, list_addons())
        return

    _print_default(lockfile, list_addons(), project_dir)


def _print_available(
    templates: list[tuple[str, str]],
    addons: Sequence[AddonMeta],
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


def _print_project_header(lockfile: ZenitLockfile, project_dir: Path) -> None:
    """Print the project name, template, and version header."""
    version_label = lockfile.zenit_version or "unknown"
    print(f"\n  {BOLD}Project{RESET}   {project_dir.name}")
    print(f"  {BOLD}Template{RESET}  {CYAN}{lockfile.template}{RESET}")
    print(f"  {BOLD}Version{RESET}   {DIM}zenit {version_label}{RESET}")


def _print_installed(
    lockfile: ZenitLockfile,
    project_dir: Path,
) -> None:
    _print_project_header(lockfile, project_dir)

    if lockfile.addons:
        print(f"\n  {BOLD}Installed addons{RESET}")
        for addon_id in lockfile.addons:
            print(f"    {GREEN}✓{RESET}  {addon_id}")
    else:
        print(f"\n  {DIM}No addons installed.{RESET}")
    print()


def _print_default(
    lockfile: ZenitLockfile,
    addons: Sequence[AddonMeta],
    project_dir: Path,
) -> None:
    _print_project_header(lockfile, project_dir)

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
    from zenit.config.config import config_path, load_config

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
        list[str] | None,
        typer.Argument(
            help="Addon(s) to add (space or comma-separated, omit for interactive selection)"
        ),
    ] = None,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip confirmation prompt"),
    ] = False,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Preview without writing anything")
    ] = False,
) -> None:
    """Add addon(s) to an existing zenit project in the current directory.

    Run without arguments to select addons interactively.
    """
    project_dir = Path.cwd()
    if addon is None:
        from zenit.addons.add import add_addon_interactive

        add_addon_interactive(dry_run=dry_run, yes=yes, project_dir=project_dir)
    else:
        from zenit.addons._registry import list_addons
        from zenit.addons.add import add_addon
        from zenit.core.dependency import DependencyGraph

        parsed = _parse_addon_list(addon) or []
        available_meta = list_addons()
        known_ids = {m.id for m in available_meta}
        unknown = [a for a in parsed if a not in known_ids]
        if unknown:
            add_addon(unknown[0], dry_run=dry_run, yes=yes, project_dir=project_dir)
            return

        from zenit.core.rollback import batch_snapshot

        graph = DependencyGraph.build_from_meta(available_meta)
        sorted_ids = list(graph.tsort(set(parsed)))
        if len(sorted_ids) > 1:
            with batch_snapshot(project_dir, f"addons: {', '.join(sorted_ids)}"):
                for addon_id in sorted_ids:
                    add_addon(
                        addon_id, dry_run=dry_run, yes=yes, project_dir=project_dir
                    )
        else:
            for addon_id in sorted_ids:
                add_addon(addon_id, dry_run=dry_run, yes=yes, project_dir=project_dir)


@app.command("remove")
def cmd_remove(
    addon: Annotated[
        list[str] | None,
        typer.Argument(
            help="Addon(s) to remove (space or comma-separated, omit for interactive selection)"
        ),
    ] = None,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip confirmation prompt"),
    ] = False,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Preview without writing anything")
    ] = False,
) -> None:
    """Remove addon(s) from an existing zenit project in the current directory.

    Run without arguments to select addons interactively.
    """
    project_dir = Path.cwd()
    if addon is None:
        from zenit.addons.remove import remove_addon_interactive

        remove_addon_interactive(dry_run=dry_run, yes=yes, project_dir=project_dir)
    else:
        from zenit.addons._registry import list_addons
        from zenit.addons.remove import remove_addon
        from zenit.core.dependency import DependencyGraph
        from zenit.schema.exceptions import ZenitError

        parsed = _parse_addon_list(addon) or []
        available_meta = list_addons()
        known_ids = {m.id for m in available_meta}
        unknown = [a for a in parsed if a not in known_ids]
        if unknown:
            try:
                remove_addon(
                    unknown[0], dry_run=dry_run, yes=yes, project_dir=project_dir
                )
            except ZenitError as exc:
                from zenit.cli.ui import error

                error(str(exc))
                raise typer.Exit(1) from exc
            return

        from zenit.core.rollback import batch_snapshot

        graph = DependencyGraph.build_from_meta(available_meta)
        sorted_ids = list(graph.tsort_reverse(set(parsed)))
        if len(sorted_ids) > 1:
            with batch_snapshot(project_dir, f"addons: {', '.join(sorted_ids)}"):
                for addon_id in sorted_ids:
                    _remove_one(addon_id, dry_run, yes, project_dir)
        else:
            for addon_id in sorted_ids:
                _remove_one(addon_id, dry_run, yes, project_dir)


def _remove_one(
    addon_id: str,
    dry_run: bool,
    yes: bool,
    project_dir: Path,
) -> None:
    """Thin wrapper: call *remove_addon*, convert ``ZenitError`` to exit."""
    from zenit.addons.remove import remove_addon
    from zenit.schema.exceptions import ZenitError

    try:
        remove_addon(addon_id, dry_run=dry_run, yes=yes, project_dir=project_dir)
    except ZenitError as exc:
        from zenit.cli.ui import error

        error(str(exc))
        raise typer.Exit(1) from exc


@app.command("doctor")
def cmd_doctor(
    fix: Annotated[
        bool,
        typer.Option("--fix", help="Fix stale line numbers in the manifest"),
    ] = False,
) -> None:
    """Check that the current project matches zenit's expectations."""
    from zenit.core.lockfile import read_lockfile
    from zenit.doctor.doctor import print_results, run_doctor

    project_dir = Path.cwd()
    lockfile = read_lockfile(project_dir)

    if lockfile is None:
        from zenit.cli.ui import error

        error(
            "No .zenit.toml found. 'zenit doctor' only works in projects scaffolded by zenit."
        )
        raise typer.Exit(1)

    print(f"\n  Checking project '{project_dir.name}'…")
    if fix:
        print(f"  {DIM}Fixing stale line numbers in the manifest.{RESET}")

    results = run_doctor(project_dir, fix=fix)

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


@app.command("migrate")
def cmd_migrate(
    source: Annotated[
        str,
        typer.Argument(
            help="Copier template source (GitHub URL, gh:user/repo, or local path)"
        ),
    ],
    name: Annotated[
        str | None,
        typer.Option(
            "--name",
            "-n",
            help="Project name (non-interactive mode; uses defaults for other questions)",
        ),
    ] = None,
    data: Annotated[
        list[str] | None,
        typer.Option(
            "--data",
            "-D",
            help="Override a template question: -D use_redis=yes (can be repeated)",
        ),
    ] = None,
) -> None:
    """Create a new project from a Copier template.

    Migrates a Copier template into a zenit-managed project with
    inventory-bootstrapped manifest entries.  The project directory is
    created in the current working directory and named after the user's
    project_name answer to the Copier questions.

    In non-interactive mode (\fB--name\fR or \fB--data\fR) every question
    takes its default value; use \fB--data\fR to override specific ones.
    """
    from zenit.migrate.migrate import run_migration

    overrides = _parse_data_flags(data) if data else None

    try:
        result = run_migration(source, name=name, data=overrides)
        _print_migration_result(result)
    except Exception as exc:
        from zenit.cli.ui import error

        error(str(exc))
        raise typer.Exit(1) from exc


def _print_migration_result(result: object) -> None:
    """Print migration result — imported lazily to avoid circular imports."""
    from zenit.migrate.migrate import MigrationResult, _print_migration_report

    if isinstance(result, MigrationResult):
        _print_migration_report(result)


@app.command("graph")
def cmd_graph(
    all_: Annotated[
        bool,
        typer.Option("--all", "-a", help="Show all available addons"),
    ] = False,
    reverse: Annotated[
        bool,
        typer.Option("--reverse", "-r", help="Show who depends on each addon"),
    ] = False,
    dot: Annotated[
        bool,
        typer.Option("--dot", help="Output Graphviz DOT format"),
    ] = False,
    json: Annotated[
        bool,
        typer.Option("--json", help="Output JSON"),
    ] = False,
) -> None:
    """Show the addon dependency graph."""
    from zenit.addons._registry import list_addons
    from zenit.cli.graph import build_tree, render_dot, render_json, render_terminal
    from zenit.core.lockfile import read_lockfile

    project_dir = Path.cwd()
    lockfile = read_lockfile(project_dir)
    all_addons = list_addons()

    installed_ids: set[str] = set(lockfile.addons) if lockfile is not None else set()

    if all_:
        displayed_addons = all_addons
    elif lockfile is not None:
        displayed_addons = [a for a in all_addons if a.id in installed_ids]
    else:
        from zenit.cli.ui import error

        error("No .zenit.toml found. Use --all to see the full ecosystem.")
        raise typer.Exit(1)

    if not displayed_addons:
        from zenit.cli.ui import info

        info("No addons to show.")
        raise typer.Exit()

    forest = build_tree(
        displayed_addons,
        installed_ids=installed_ids,
        reverse=reverse,
    )

    if dot:
        print(render_dot(forest), end="")
        return

    if json:
        print(
            render_json(
                forest,
                installed_ids=installed_ids,
                all_addons=all_addons,
                project_name=project_dir.name if lockfile is not None else None,
                project_dir=str(project_dir) if lockfile is not None else None,
                template=lockfile.template if lockfile is not None else None,
            ),
            end="",
        )
        return

    print(
        render_terminal(
            forest,
            installed_ids=installed_ids,
            project_name=project_dir.name if lockfile is not None else None,
            project_dir=str(project_dir) if lockfile is not None else None,
            reverse=reverse,
        ),
        end="",
    )


def main() -> None:
    app()


if __name__ == "__main__":
    main()
