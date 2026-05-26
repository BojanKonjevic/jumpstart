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
from zenit.core.lockfile import ZenitLockfile, read_lockfile, write_lockfile
from zenit.core.manifest import (
    read_manifest,
    record_addon_manifest_entries,
    write_manifest,
)
from zenit.core.pkg_name import normalise_pkg_name, resolve_dest_placeholder
from zenit.core.render import build_recipe_render_vars, build_render_vars, make_env
from zenit.core.rollback import addon_or_rollback
from zenit.schema.exceptions import ZenitError
from zenit.schema.models import (
    AddonConfig,
    ComposeService,
    EntrySource,
    Manifest,
    TemplateConfig,
)
from zenit.templates._load_config import load_template_config


@dataclass
class _AddResult:
    """Result of running the add-on pipeline."""

    added_deps: list[str] = field(default_factory=list)
    added_dev_deps: list[str] = field(default_factory=list)
    added_env_vars: list[str] = field(default_factory=list)
    added_recipes: list[str] = field(default_factory=list)
    recorded_files: list[tuple[str, str, str]] = field(default_factory=list)


def _template_file_overrides(
    addon_cfg: AddonConfig,
    template_paths: list[str],
    pkg_name: str,
) -> list[str]:
    """Return addon file destinations that would override presence-tracked files."""
    tracked_set = set(template_paths)
    return [
        resolve_dest_placeholder(fc.dest, pkg_name)
        for fc in addon_cfg.files
        if resolve_dest_placeholder(fc.dest, pkg_name) in tracked_set
    ]


def _run_add_pipeline(
    ctx: Context,
    fs: FileSystem,
    addon_cfg: AddonConfig,
    installed_addons: list[str] | None = None,
    *,
    lockfile_override: ZenitLockfile | None = None,
) -> _AddResult:
    """Shared pipeline body for both real and dry-run add operations.

    Parameters
    ----------
    installed_addons:
        Addons already present in the lockfile.  Used to decide whether
        docker-managed compose contributions are allowed.  Pass the
        lockfile's ``addons`` list; omitted during dry runs.
    """

    zenit_root = ctx.zenit_root
    template = ctx.template
    pkg_name = ctx.pkg_name
    project_dir = ctx.project_dir

    try:
        template_config = load_template_config(zenit_root, template)
    except (FileNotFoundError, ZenitError):
        template_config = TemplateConfig(id="migrated", description="migrated project")
    contributions = collect_addon_only([addon_cfg])

    # Docker owns all compose services and volumes. Non-docker addons declare
    # their compose needs in AddonConfig but never directly merge or own
    # compose entries — that is docker's job via _refresh_compose.
    if addon_cfg.id != "docker":
        contributions.compose_services = []
        contributions.compose_volumes = []

    render_vars = build_render_vars(
        name=ctx.name,
        pkg_name=pkg_name,
        template=template,
        addons=ctx.addons,
        deps=contributions.deps,
        dev_deps=contributions.dev_deps,
    )

    # Read .zenit.toml once and pass it down to avoid redundant parse.
    manifest = Manifest() if ctx.dry_run else read_manifest(project_dir)

    apply_contributions(
        ctx,
        fs,
        contributions,
        template_config.injection_points,
        render_vars,
        manifest=manifest if not ctx.dry_run else None,
        lockfile=lockfile_override,
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
        upgraded = record_addon_manifest_entries(
            manifest,
            addon_cfg,
            string_env,
            render_vars,
        )
        write_manifest(project_dir, manifest)
        for u in upgraded:
            info(
                f"Transferred ownership of {u} from Copier template "
                f"to addon '{addon_cfg.id}'."
            )

    # ── Env vars ──────────────────────────────────────────────────────────────
    added_env_vars = [ev.key for ev in contributions.env_vars]

    # ── Recorded files (dry-run only) ─────────────────────────────────────────
    recorded_files = list(fs.recorded_files) if ctx.dry_run else []  # type: ignore[attr-defined]

    return _AddResult(
        added_deps=added_deps,
        added_dev_deps=added_dev_deps,
        added_env_vars=added_env_vars,
        added_recipes=added_recipes,
        recorded_files=recorded_files,
    )


def _refresh_compose(
    ctx: Context,
    project_dir: Path,
    manifest: Manifest,
) -> None:
    """Reconcile compose.yml and manifest with all installed addons' compose entries.

    Docker owns all compose entries. This function:
    1. Collects compose services/volumes from all installed addons.
    2. Removes stale ADDON-source entries from compose.yml.
    3. Merges current entries into compose.yml.
    4. Records all entries as docker-owned in the manifest.
    """
    from io import StringIO

    from ruamel.yaml import YAML

    from zenit.addons._registry import get_addon as _get_addon
    from zenit.core._filenames import COMPOSE_FILE
    from zenit.core.apply import merge_compose_into_data
    from zenit.core.manifest import add_compose_service, add_compose_volume
    from zenit.core.pkg_name import resolve_dest_placeholder

    _compose_yaml = YAML()
    _compose_yaml.default_flow_style = False

    def _dump(data: object) -> str:
        buf = StringIO()
        _compose_yaml.dump(data, buf)
        return buf.getvalue()

    compose_path = project_dir / COMPOSE_FILE
    if not compose_path.exists():
        return

    # 1. Collect compose from all installed addons
    services: list[ComposeService] = []
    volumes: list[str] = []
    for addon_id in ctx.addons:
        addon_cfg = _get_addon(addon_id)
        services.extend(addon_cfg.compose_services)
        volumes.extend(addon_cfg.compose_volumes)

    # Resolve {{pkg_name}} placeholders in service fields
    for svc in services:
        if svc.command and "{{pkg_name}}" in svc.command:
            svc.command = resolve_dest_placeholder(svc.command, ctx.pkg_name)
        if svc.environment:
            svc.environment = {
                k: resolve_dest_placeholder(v, ctx.pkg_name)
                if isinstance(v, str)
                else v
                for k, v in svc.environment.items()
            }
        if svc.develop_watch:
            for watch in svc.develop_watch:
                if "path" in watch and isinstance(watch["path"], str):
                    watch["path"] = resolve_dest_placeholder(
                        watch["path"], ctx.pkg_name
                    )

    # 2. Single read-modify-write cycle
    old_service_names = {
        e.name for e in manifest.compose_services if e.source == EntrySource.ADDON
    }
    old_volume_names = {
        e.name for e in manifest.compose_volumes if e.source == EntrySource.ADDON
    }
    data: dict[str, object] = (
        _compose_yaml.load(compose_path.read_text(encoding="utf-8")) or {}
    )
    svc_section: dict[str, object] = data.get("services", {})  # type: ignore[assignment]
    vol_section: dict[str, object] = data.get("volumes", {})  # type: ignore[assignment]
    for name in old_service_names:
        svc_section.pop(name, None)
    for name in old_volume_names:
        vol_section.pop(name, None)

    merge_compose_into_data(data, services, volumes)
    from zenit.core.filesystem import atomic_write_text

    atomic_write_text(compose_path, _dump(data))

    # 3. Update manifest — record all entries as docker-owned
    manifest.compose_services = [
        e for e in manifest.compose_services if e.source != EntrySource.ADDON
    ]
    manifest.compose_volumes = [
        e for e in manifest.compose_volumes if e.source != EntrySource.ADDON
    ]
    for svc in services:
        add_compose_service(manifest, svc.name, EntrySource.ADDON, "docker")
    for vol in volumes:
        add_compose_volume(manifest, vol, EntrySource.ADDON, "docker")


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
        if lockfile.template_file_paths:
            overrides = _template_file_overrides(
                addon_cfg, lockfile.template_file_paths, pkg_name
            )
            if overrides:
                warn(
                    "Addon overrides presence-tracked Copier template files: "
                    + ", ".join(overrides)
                )
        result = _run_add_pipeline(ctx, fs, addon_cfg, installed_addons=lockfile.addons)

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

        if result.added_env_vars:
            dry_header("Environment variables that would be added")
            for ev in result.added_env_vars:
                dry_dep(ev)

        print()
        return

    addon_cfg = get_addon(addon_id)

    # ── Warn about overrides of presence-tracked Copier template files ─────
    if lockfile.template_file_paths:
        overrides = _template_file_overrides(
            addon_cfg, lockfile.template_file_paths, pkg_name
        )
        if overrides:
            warn(
                "This addon will override files from the Copier template: "
                + ", ".join(overrides)
            )

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
        result = _run_add_pipeline(
            ctx,
            fs,
            addon_cfg,
            installed_addons=lockfile.addons,
            lockfile_override=lockfile,
        )
        write_lockfile(
            project_dir,
            template,
            ctx.addons,
            template_source=lockfile.template_source,
            template_uri=lockfile.template_uri,
            template_has_tasks=lockfile.template_has_tasks,
            template_file_paths=lockfile.template_file_paths,
        )

    # ── Refresh compose (docker-owned reconciliation) ─────────────────────────
    if "docker" in ctx.addons:
        manifest = read_manifest(project_dir)
        _refresh_compose(ctx, project_dir, manifest)
        write_manifest(project_dir, manifest)

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

    if result.added_env_vars:
        bullet_list(
            "Env vars added:", result.added_env_vars, bullet="+", bullet_color=GREEN
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
