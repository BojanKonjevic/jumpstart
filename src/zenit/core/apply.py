"""Apply collected contributions to the project directory."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from jinja2 import Environment

from zenit.core.handlers.base import HandlerDispatcher
from zenit.core.handlers.justfile_handler import _RECIPE_NAME_RE
from zenit.core.manifest import (
    add_compose_service,
    add_compose_volume,
    add_dependency,
    add_env_entry,
    add_just_recipe,
    add_python_block,
    fingerprint,
    read_manifest,
    write_manifest,
)
from zenit.core.pkg_name import resolve_dest_placeholder
from zenit.core.render import make_env
from zenit.schema.exceptions import ZenitError
from zenit.schema.models import EntrySource, LocatorSpec, Manifest, ManifestBlock

if TYPE_CHECKING:
    from zenit.core.context import Context
    from zenit.schema.models import (
        AddonConfig,
        ComposeService,
        Contributions,
        EnvVar,
        InjectionPoint,
    )


def _pkg_name(dep: str) -> str:
    """Canonical package-name extractor for PEP 508 dependency specifiers.

    Handles >=, ==, !=, ~=, extras ([...]), environment markers (;), and
    URL references (@).  Normalises separators to underscores so that
    'my-package' and 'my_package' compare equal.
    """
    return re.split(r"[>=<!,; \[@]", dep)[0].strip().lower().replace("-", "_")


def apply_contributions(
    ctx: Context,
    contributions: Contributions,
    injection_points: dict[str, InjectionPoint],
    render_vars: dict[str, object],
) -> None:
    """Modify the generated project directory in-place according to *contributions*.

    Assumes common files have already been placed via ``_common/apply.py``.
    Steps (in order):

    1. Create directories.
    2. Write / copy / render individual files.
    3. Apply structural injections (via HandlerDispatcher) and record in manifest.
    4. Merge compose services and volumes into ``compose.yml`` (if present).
    5. Append env vars to ``.env`` and ``.env.example`` (if present).
    6. Record per-addon manifest entries (env, compose, deps, recipes).
    7. Run each addon's optional ``post_apply`` hook.
    8. Write updated manifest to .zenit.toml.

    Template-owned entries (env vars, compose services/volumes, deps, recipes)
    are recorded separately by ``_stamp_template_manifest`` in scaffold.py and
    are NOT recorded here — ``contributions`` may contain template items merged
    in from ``collect_all``, but ownership of those belongs to the template, not
    to any addon.
    """
    project_dir = ctx.project_dir
    pkg_name = str(render_vars["pkg_name"])

    for d in contributions.dirs:
        ctx.create_dir(resolve_dest_placeholder(d, pkg_name))

    # Pre-render {{pkg_name}} placeholders in compose service fields
    for svc in contributions.compose_services:
        if svc.command and "{{pkg_name}}" in svc.command:
            svc.command = resolve_dest_placeholder(svc.command, pkg_name)
        if svc.environment:
            svc.environment = {
                k: resolve_dest_placeholder(v, pkg_name) if isinstance(v, str) else v
                for k, v in svc.environment.items()
            }
        if svc.develop_watch:
            for watch in svc.develop_watch:
                if "path" in watch and isinstance(watch["path"], str):
                    watch["path"] = resolve_dest_placeholder(watch["path"], pkg_name)

    for fc in contributions.files:
        dest = resolve_dest_placeholder(fc.dest, pkg_name)
        if fc.content is not None:
            if fc.template:
                string_env = make_env()
                rendered = string_env.from_string(fc.content).render(**render_vars)
                ctx.write_file(dest, rendered)
            else:
                ctx.write_file(dest, fc.content)
        elif fc.source is not None:
            src_path = Path(fc.source)
            if not src_path.is_absolute():
                raise ZenitError(
                    f"Internal error: the source path for '{fc.dest}' is relative ('{fc.source}'). "
                    f"FileContribution.source must be an absolute path. "
                    f"This is a bug in the template or addon — please report it."
                )
            if fc.template:
                env = make_env(src_path.parent)
                content = env.get_template(src_path.name).render(**render_vars)
                ctx.write_file(dest, content)
            else:
                ctx.copy_file(src_path, dest)

    manifest = read_manifest(project_dir)
    dispatcher = HandlerDispatcher()

    for inj in contributions.injections:
        point = injection_points.get(inj.point)
        if point is None:
            continue

        resolved_file = resolve_dest_placeholder(point.file, pkg_name)
        file_path = project_dir / resolved_file

        if not file_path.exists():
            continue

        string_env = make_env()
        rendered_content = string_env.from_string(inj.content).render(**render_vars)

        _, start_line, end_line = dispatcher.apply(
            file_path,
            rendered_content,
            point.locator.name,
            dict(point.locator.args),
        )

        # Only Python files get fingerprint-tracked ManifestBlocks.
        if file_path.suffix == ".py":
            # Read back the written file so the fingerprint covers the actual
            # bytes on disk (libcst may normalise whitespace during round-trip).
            fresh_lines = file_path.read_text(encoding="utf-8").splitlines(
                keepends=True
            )
            block_text = "".join(fresh_lines[start_line - 1 : end_line])
            fp, fp_norm = fingerprint(block_text)
            block = ManifestBlock(
                addon=inj.addon_id,
                point=inj.point,
                file=resolved_file,
                lines=f"{start_line}-{end_line}",
                fingerprint=fp,
                fingerprint_normalised=fp_norm,
                locator=LocatorSpec(
                    name=point.locator.name,
                    args=dict(point.locator.args),
                ),
            )
            add_python_block(manifest, block)

    if contributions.compose_services and (project_dir / "compose.yml").exists():
        _merge_compose(ctx, contributions.compose_services, contributions.compose_volumes)

    for file_name in (".env", ".env.example"):
        if (project_dir / file_name).exists() and contributions.env_vars:
            _merge_env_vars(ctx, file_name, contributions.env_vars)

    # ── Per-addon manifest recording ──────────────────────────────────────────
    #
    # We iterate each AddonConfig directly so that every manifest entry carries
    # the correct addon_id.  Using the merged flat lists on `contributions` with
    # a single addon_id derived from _addon_configs[0] would assign all entries
    # to one addon when multiple addons are applied together (e.g. at scaffold
    # time via collect_all), corrupting ownership metadata.
    #
    # Template-owned entries are intentionally excluded here: _stamp_template_manifest
    # in scaffold.py records those with source="template", addon="" after write_lockfile.
    # Doing it here would double-record them on every scaffold run.
    string_env = make_env()
    for addon_cfg in contributions._addon_configs:
        _record_addon_manifest_entries(manifest, addon_cfg, string_env, render_vars)

    for addon_cfg in contributions._addon_configs:
        hooks = addon_cfg._module
        if hooks is not None and hooks.post_apply is not None:
            hooks.post_apply(ctx)

    if not ctx.dry_run:
        write_manifest(project_dir, manifest)


# ── Manifest recording ────────────────────────────────────────────────────────


def _record_addon_manifest_entries(
    manifest: Manifest,
    addon_cfg: AddonConfig,
    string_env: Environment,
    render_vars: dict[str, object],
) -> None:
    """Record all non-Python manifest entries owned by *addon_cfg*.

    Python block entries are recorded inline in the injection loop above,
    because they require the post-write line numbers and fingerprints that
    are only available at injection time.
    """

    addon_id = addon_cfg.id

    for ev in addon_cfg.env_vars:
        add_env_entry(manifest, ev.key, source=EntrySource.ADDON, addon=addon_id)

    for svc in addon_cfg.compose_services:
        add_compose_service(manifest, svc.name, source=EntrySource.ADDON, addon=addon_id)

    for vol in addon_cfg.compose_volumes:
        add_compose_volume(manifest, vol, source=EntrySource.ADDON, addon=addon_id)

    for dep in addon_cfg.deps:
        add_dependency(
            manifest,
            _pkg_name(dep),
            dep,
            source=EntrySource.ADDON,
            addon=addon_id,
            dev=False,
        )

    for dep in addon_cfg.dev_deps:
        add_dependency(
            manifest,
            _pkg_name(dep),
            dep,
            source=EntrySource.ADDON,
            addon=addon_id,
            dev=True,
        )

    for recipe_raw in addon_cfg.just_recipes:
        rendered = string_env.from_string(recipe_raw).render(**render_vars)
        m = _RECIPE_NAME_RE.search(rendered)
        if m:
            add_just_recipe(manifest, m.group(1), source=EntrySource.ADDON, addon=addon_id)


# ── Internal helpers ──────────────────────────────────────────────────────────


def _merge_compose(
    ctx: Context,
    services: list[ComposeService],
    volumes: list[str],
) -> None:
    """Add *services* and *volumes* to ``compose.yml``, skipping duplicates."""
    compose_path = ctx.project_dir / "compose.yml"
    data: dict[str, Any] = (
        yaml.safe_load(compose_path.read_text(encoding="utf-8")) or {}
    )

    existing: dict[str, Any] = data.setdefault("services", {})
    for svc in services:
        if svc.name in existing:
            continue
        block: dict[str, Any] = {}
        if svc.image:
            block["image"] = svc.image
        if svc.build:
            block["build"] = svc.build
        if svc.ports:
            block["ports"] = svc.ports
        if svc.volumes:
            block["volumes"] = svc.volumes
        if svc.environment:
            block["environment"] = svc.environment
        if svc.env_file:
            block["env_file"] = svc.env_file
        if svc.command:
            block["command"] = svc.command
        if svc.depends_on:
            block["depends_on"] = svc.depends_on
        if svc.develop_watch:
            develop = block.setdefault("develop", {})
            if isinstance(develop, dict):
                develop["watch"] = svc.develop_watch
        if svc.healthcheck:
            block["healthcheck"] = svc.healthcheck
        existing[svc.name] = block

    vols_section: dict[str, Any] = data.setdefault("volumes", {})
    for vol_name in volumes:
        if vol_name not in vols_section:
            vols_section[vol_name] = None

    ctx.write_file(
        "compose.yml",
        yaml.dump(data, default_flow_style=False, sort_keys=False),
    )


def _merge_env_vars(ctx: Context, file_name: str, env_vars: list[EnvVar]) -> None:
    """Append missing env vars to the end of *file_name* via *ctx*."""
    env_path = ctx.project_dir / file_name
    text = env_path.read_text(encoding="utf-8")

    existing_keys = {
        line.split("=", 1)[0].strip()
        for line in text.splitlines()
        if "=" in line and not line.strip().startswith("#")
    }

    new_lines: list[str] = []
    for v in env_vars:
        if v.key not in existing_keys:
            line = f"{v.key}={v.default}"
            if v.comment:
                line += f"  # {v.comment}"
            new_lines.append(line)

    if new_lines:
        text = text.rstrip("\n") + "\n" + "\n".join(new_lines) + "\n"
        ctx.write_file(file_name, text)
