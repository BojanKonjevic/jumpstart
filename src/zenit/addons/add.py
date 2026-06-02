"""Add‑on pipeline — apply a single addon to an existing project."""

from __future__ import annotations

import dataclasses
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
from zenit.core.constants import extract_recipe_name
from zenit.core.context import Context
from zenit.core.dependency import DependencyGraph
from zenit.core.deps import inject_deps
from zenit.core.filesystem import FileSystem, RealFileSystem, RecordingFileSystem
from zenit.core.justfile import inject_just_recipes
from zenit.core.lockfile import ZenitLockfile, read_lockfile, write_zenit_toml
from zenit.core.manifest import (
    add_just_recipe,
    read_manifest,
    record_addon_manifest_entries,
)
from zenit.core.pkg_name import (
    normalise_pkg_name,
    resolve_compose_placeholders,
    resolve_dest_placeholder,
)
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
) -> tuple[_AddResult, Manifest | None]:
    """Shared pipeline body for both real and dry-run add operations.

    Returns ``(result, manifest)`` where *manifest* is ``None`` during
    dry runs — the caller is responsible for writing the manifest and
    lockfile via ``write_zenit_toml``.

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

    python_version = f"{sys.version_info.major}.{sys.version_info.minor}"
    render_vars = build_render_vars(
        name=ctx.name,
        pkg_name=pkg_name,
        template=template,
        addons=ctx.addons,
        deps=contributions.deps,
        dev_deps=contributions.dev_deps,
        python_version=python_version,
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
        python_version=python_version,
    )
    string_env = make_env()
    rendered_recipes = [
        string_env.from_string(r).render(**recipe_render_vars)
        for r in contributions.recipes.addon
    ]

    if ctx.dry_run:
        added_recipes = [n for r in rendered_recipes if (n := extract_recipe_name(r))]
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
        for u in upgraded:
            info(
                f"Transferred ownership of {u} from Copier template "
                f"to addon '{addon_cfg.id}'."
            )

    # ── Env vars ──────────────────────────────────────────────────────────────
    added_env_vars = [ev.key for ev in contributions.env_vars]

    # ── Recorded files (dry-run only) ─────────────────────────────────────────
    recorded_files = list(fs.recorded_files) if ctx.dry_run else []  # type: ignore[attr-defined]

    return (
        _AddResult(
            added_deps=added_deps,
            added_dev_deps=added_dev_deps,
            added_env_vars=added_env_vars,
            added_recipes=added_recipes,
            recorded_files=recorded_files,
        ),
        manifest if not ctx.dry_run else None,
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
    from zenit.addons._registry import get_addon as _get_addon
    from zenit.core._filenames import COMPOSE_FILE
    from zenit.core.apply import merge_compose_into_data
    from zenit.core.manifest import add_compose_service, add_compose_volume
    from zenit.core.yaml_utils import compose_yaml_dumps as _compose_yaml_dumps
    from zenit.core.yaml_utils import compose_yaml_load as _compose_yaml_load

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
    resolve_compose_placeholders(services, ctx.pkg_name)

    # 2. Single read-modify-write cycle
    old_service_names = {
        e.name for e in manifest.compose_services if e.source == EntrySource.ADDON
    }
    old_volume_names = {
        e.name for e in manifest.compose_volumes if e.source == EntrySource.ADDON
    }
    data: dict[str, object] = (
        _compose_yaml_load(compose_path.read_text(encoding="utf-8")) or {}
    )
    svc_section: dict[str, object] = data.get("services", {})  # type: ignore[assignment]
    vol_section: dict[str, object] = data.get("volumes", {})  # type: ignore[assignment]
    for name in old_service_names:
        svc_section.pop(name, None)
    for name in old_volume_names:
        vol_section.pop(name, None)

    merge_compose_into_data(data, services, volumes)

    # 3. Reconcile app service environment and depends_on (before write)
    _reconcile_app_service_env(data, ctx, manifest)

    from zenit.core.filesystem import atomic_write_text

    atomic_write_text(compose_path, _compose_yaml_dumps(data))

    # 4. Update manifest — record all entries as docker-owned
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


def _reconcile_app_service_env(
    data: dict[str, object],
    ctx: Context,
    manifest: Manifest,
) -> None:
    """Reconcile the ``app`` service's ``environment`` and ``depends_on``.

    Adds env vars and depends_on entries contributed by currently installed
    addons, and removes stale entries from addons that are no longer present.
    """
    from zenit.addons._registry import get_addon as _get_addon
    from zenit.core.manifest import (
        add_compose_app_depends_on as _add_dep,
    )
    from zenit.core.manifest import (
        add_compose_app_env as _add_env,
    )

    services_data: dict[str, object] = data.get("services", {})  # type: ignore[assignment]
    if "app" not in services_data:
        services_data["app"] = {}
    app_svc: dict[str, object] = services_data["app"]  # type: ignore[assignment]

    # 4a. Collect active compose_app_env from installed addons
    active_env: dict[str, str] = {}
    for addon_id in ctx.addons:
        cfg = _get_addon(addon_id)
        active_env.update(cfg.compose_app_env)

    # Resolve placeholders
    active_env = {
        k: v.replace("(( pkg_name ))", ctx.pkg_name) for k, v in active_env.items()
    }

    # 4b. Reconcile environment block
    stale_env_keys = {
        e.key for e in manifest.compose_app_env if e.key not in active_env
    }
    current_env: dict[str, object] | None = app_svc.get("environment")  # type: ignore[assignment]
    if current_env is not None and isinstance(current_env, dict):
        for key in stale_env_keys:
            current_env.pop(key, None)
        current_env.update(active_env)
        if not current_env:
            del app_svc["environment"]
    elif active_env:
        app_svc["environment"] = dict(active_env)
    # 4c. Update manifest entries for compose_app_env
    manifest.compose_app_env = [
        e for e in manifest.compose_app_env if e.key not in stale_env_keys
    ]
    active_keys = set(active_env)
    for key in active_keys:
        _add_env(manifest, key, EntrySource.ADDON, "docker")

    # 4d. Collect active compose_app_depends_on
    active_dep: dict[str, dict[str, str]] = {}
    for addon_id in ctx.addons:
        cfg = _get_addon(addon_id)
        active_dep.update(cfg.compose_app_depends_on)

    # 4e. Reconcile depends_on block
    stale_dep_names = {
        e.name for e in manifest.compose_app_depends_on if e.name not in active_dep
    }
    current_dep: dict[str, object] | None = app_svc.get("depends_on")  # type: ignore[assignment]
    if current_dep is not None and isinstance(current_dep, dict):
        for name in stale_dep_names:
            current_dep.pop(name, None)
        current_dep.update(active_dep)
        if not current_dep:
            del app_svc["depends_on"]
    elif active_dep:
        app_svc["depends_on"] = dict(active_dep)
    # 4f. Update manifest entries for compose_app_depends_on
    manifest.compose_app_depends_on = [
        e for e in manifest.compose_app_depends_on if e.name not in stale_dep_names
    ]
    for name in active_dep:
        _add_dep(manifest, name, EntrySource.ADDON, "docker")


def _backfill_just_recipes(
    ctx: Context,
    project_dir: Path,
    manifest: Manifest,
    addon_id: str,
) -> list[str]:
    """Re-render just-recipes for earlier addons when the addon set changes.

    When Docker is added to a project, addons whose recipes were gated on
    ``[% if "docker" in addons %]`` need their recipes backfilled — they
    rendered to empty strings (or native branches) during their own add
    pipeline because docker was not present at the time.

    When Docker is removed from a project, the reverse — docker-gated
    recipes are replaced with native alternatives from the ``[% else %]``
    branch, or removed entirely if no native fallback exists.

    Removes existing recipes for each target addon before injecting the
    re-rendered versions so that ``inject_just_recipes`` doesn't skip them
    as duplicates.

    Returns the list of recipe names that were added to the justfile.
    """
    from zenit.addons.remove import _remove_just_recipes

    python_version = f"{sys.version_info.major}.{sys.version_info.minor}"
    all_added: list[str] = []

    for installed_id in ctx.addons:
        if installed_id == addon_id:
            continue

        installed_cfg = get_addon(installed_id)
        if not installed_cfg.just_recipes:
            continue

        _remove_just_recipes(project_dir, manifest, installed_id)

        recipe_render_vars = build_recipe_render_vars(
            name=ctx.name,
            pkg_name=ctx.pkg_name,
            template=ctx.template,
            addons=ctx.addons,
            deps=installed_cfg.deps,
            dev_deps=installed_cfg.dev_deps,
            python_version=python_version,
        )
        string_env = make_env()
        rendered_recipes = [
            string_env.from_string(r).render(**recipe_render_vars)
            for r in installed_cfg.just_recipes
        ]
        added = inject_just_recipes(project_dir, rendered_recipes)
        all_added.extend(added)
        for name in added:
            add_just_recipe(manifest, name, EntrySource.ADDON, installed_id)

    return all_added


def add_addon(
    addon_id: str,
    dry_run: bool = False,
    yes: bool = False,
    accept_overwrites: bool = False,
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
    addon_cfg = get_addon(addon_id)

    # ── Warn about overrides of presence-tracked Copier template files ─────
    overrides: list[str] = []
    if lockfile.template_file_paths:
        overrides = _template_file_overrides(
            addon_cfg, lockfile.template_file_paths, pkg_name
        )

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
        if overrides:
            warn(
                "Addon overrides presence-tracked Copier template files: "
                + ", ".join(overrides)
            )
        result, _ = _run_add_pipeline(
            ctx, fs, addon_cfg, installed_addons=lockfile.addons
        )

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

    # ── Overwrite pre-check for Copier-migrated projects ──────────────────────
    if overrides and lockfile.template_source == "copier":
        if accept_overwrites or yes:
            for f in overrides:
                warn(f"Overwriting '{f}' (previously from Copier template)")
        elif not sys.stdin.isatty():
            error(
                f"Running 'zenit add' would overwrite files from the "
                f"Copier template: {', '.join(overrides)}. "
                f"Re-run with --accept-overwrites / -y to proceed."
            )
            raise typer.Exit(1)
    elif overrides:
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
    elif not yes:
        warn("Non‑interactive mode — proceeding automatically.")

    # ── Interactive per-file overwrite confirmation ──────────────────────────
    if (
        overrides
        and lockfile.template_source == "copier"
        and not accept_overwrites
        and not yes
    ):
        accept_all = False
        files_to_skip: set[str] = set()
        for f in overrides:
            if accept_all:
                warn(f"Overwriting '{f}' (accepted all)")
                continue
            raw = (
                input(f"  Overwrite '{f}' (written by Copier template)? [y/N/a(ll)]: ")
                .strip()
                .lower()
            )
            if raw == "a":
                accept_all = True
                warn(f"Overwriting '{f}' (accepted all)")
            elif raw == "y":
                warn(f"Overwriting '{f}'")
            else:
                files_to_skip.add(f)
                info(f"Skipping '{f}' — addon file not written.")

        if files_to_skip:
            addon_cfg = dataclasses.replace(
                addon_cfg,
                files=[
                    fc
                    for fc in addon_cfg.files
                    if resolve_dest_placeholder(fc.dest, pkg_name) not in files_to_skip
                ],
            )

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
        result, manifest = _run_add_pipeline(
            ctx,
            fs,
            addon_cfg,
            installed_addons=lockfile.addons,
            lockfile_override=lockfile,
        )

        # ── Refresh compose + backfill recipes (docker-owned reconciliation) ──
        if "docker" in ctx.addons and manifest is not None:
            _refresh_compose(ctx, project_dir, manifest)
            backfilled = _backfill_just_recipes(ctx, project_dir, manifest, addon_id)
            result.added_recipes.extend(backfilled)

        # ── Single atomic write of both [project] and [manifest] sections ─────
        write_zenit_toml(
            project_dir,
            template=template,
            addons=ctx.addons,
            template_source=lockfile.template_source,
            template_uri=lockfile.template_uri,
            template_has_tasks=lockfile.template_has_tasks,
            template_file_paths=lockfile.template_file_paths,
            manifest=manifest,
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

    sorted_ids = list(graph.tsort(set(selected)))
    if len(sorted_ids) > 1:
        from zenit.core.rollback import batch_snapshot

        with batch_snapshot(project_dir, f"addons: {', '.join(sorted_ids)}"):
            for addon_id in sorted_ids:
                add_addon(addon_id, dry_run=dry_run, yes=yes)
    else:
        for addon_id in sorted_ids:
            add_addon(addon_id, dry_run=dry_run, yes=yes)
