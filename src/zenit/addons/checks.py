"""Precondition checking for ``zenit add`` and ``zenit remove``.

Each addon may expose ``can_apply(project_dir, lockfile)`` and/or
``can_remove(project_dir, lockfile)`` functions in its ``addon.py``.
If present, they are called before any writes happen.

Return contract
---------------
- Return ``None`` (or don't define the function) → addon assumes operation is allowed.
- Return a non-empty string → human-readable reason why it cannot; the command
  will raise ``ZenitError`` with this message and abort.

Example in an addon.py
----------------------
    def can_apply(project_dir: Path, lockfile: ZenitLockfile) -> str | None:
        pkg_name = lockfile.template  # use lockfile to know the layout
        ...
        if (project_dir / "src").exists():
            return None
        return "No src/ directory found - this addon expects a src layout."

    def can_remove(project_dir: Path, lockfile: ZenitLockfile) -> str | None:
        if some_other_addon_depends_on_this(lockfile):
            return "Another installed addon depends on this one."
        return None
"""

from __future__ import annotations

from pathlib import Path

from zenit.addons._registry import get_addon, list_addons
from zenit.core._paths import get_zenit_root
from zenit.core.dependency import DependencyGraph
from zenit.core.lockfile import ZenitLockfile, read_lockfile
from zenit.schema.exceptions import ZenitError
from zenit.templates._load_config import load_template_config


def _known_addon_ids() -> set[str]:
    return {m.id for m in list_addons()}


def _read_lockfile_and_validate(
    project_dir: Path,
    addon_id: str,
    command: str,
) -> ZenitLockfile:
    lockfile = read_lockfile(project_dir)
    if lockfile is None:
        raise ZenitError(
            f"No .zenit.toml found. "
            f"'zenit {command}' only works in projects scaffolded by zenit."
        )
    if not lockfile.template:
        raise ZenitError(
            ".zenit.toml exists but has no template field - it may be corrupt."
        )
    addon_ids = _known_addon_ids()
    if addon_id not in addon_ids:
        known = ", ".join(sorted(addon_ids))
        raise ZenitError(f"Unknown addon '{addon_id}'. Available addons: {known}")
    return lockfile


def _is_template_compatible(
    addon_templates: list[str],
    lockfile: ZenitLockfile,
) -> bool:
    """Check whether an addon is compatible with the project's template.

    An addon with an empty ``templates`` list is compatible with everything.
    Otherwise at least one of these must match:
    - The addon lists ``"native"`` and the project's template source is ``"native"``
    - The addon lists ``"copier:*"`` and the project's template source is ``"copier"``
    - The addon lists the project's exact template name (e.g. ``"fastapi"``)
    - The addon lists the project's ``template_uri``
    """
    if not addon_templates:
        return True

    for t in addon_templates:
        if t == "native" and lockfile.template_source == "native":
            return True
        if t == "copier:*" and lockfile.template_source == "copier":
            return True
        if t == lockfile.template:
            return True
        if lockfile.template_uri and t == lockfile.template_uri:
            return True

    return False


def check_can_add(
    project_dir: Path,
    addon_id: str,
) -> ZenitLockfile:
    """Run all precondition checks for adding *addon_id* to *project_dir*.

    Returns the parsed lockfile on success (callers need it to know the
    template and currently installed addons).

    Raises ZenitError with a clear message on any failure - the caller
    just needs to print it and exit.
    """
    lockfile = _read_lockfile_and_validate(project_dir, addon_id, "add")
    available_meta = list_addons()

    # ── not already installed ─────────────────────────────────────────────────
    if addon_id in lockfile.addons:
        raise ZenitError(
            f"'{addon_id}' is already listed in .zenit.toml. "
            "If you removed it manually, edit .zenit.toml to reflect the current state."
        )

    # ── template compatibility ─────────────────────────────────────────────────
    cfg_meta = next(c for c in available_meta if c.id == addon_id)
    if not _is_template_compatible(cfg_meta.templates, lockfile):
        allowed = ", ".join(cfg_meta.templates)
        project_info = lockfile.template_uri or lockfile.template
        raise ZenitError(
            f"'{addon_id}' is only compatible with the {allowed} template, "
            f"but this project uses '{project_info}' "
            f"(source: {lockfile.template_source})."
        )

    # ── dependency addons are installed (transitive) ──────────────────────────
    graph = DependencyGraph.build_from_meta(available_meta)
    all_deps = graph.closure({addon_id}) - {addon_id}
    missing_deps = sorted(d for d in all_deps if d not in lockfile.addons)
    if missing_deps:
        missing_str = ", ".join(missing_deps)
        raise ZenitError(
            f"'{addon_id}' requires {missing_str}. "
            f"Run 'zenit add {missing_deps[0]}' first."
        )

    # ── conflicting addons are not installed ──────────────────────────────────
    conflicting = [c for c in cfg_meta.conflicts_with if c in lockfile.addons]
    if conflicting:
        conflict_str = ", ".join(conflicting)
        raise ZenitError(
            f"'{addon_id}' conflicts with {conflict_str}. Remove {conflict_str} first."
        )

    # ── addon's own can_apply check ───────────────────────────────────────────
    cfg = get_addon(addon_id)
    hooks = cfg._module
    if hooks is not None and hooks.can_apply is not None:
        reason = hooks.can_apply(project_dir, lockfile)
        if reason:
            raise ZenitError(reason)

    return lockfile


def check_can_remove(
    project_dir: Path,
    addon_id: str,
) -> ZenitLockfile:
    """Run all precondition checks for removing *addon_id* from *project_dir*.

    Returns the parsed lockfile on success (callers need it to know the
    template and currently installed addons).

    Raises ZenitError with a clear message on any failure.
    """
    lockfile = _read_lockfile_and_validate(project_dir, addon_id, "remove")
    available_meta = list_addons()

    # ── is actually installed ─────────────────────────────────────────────────
    if addon_id not in lockfile.addons:
        raise ZenitError(
            f"'{addon_id}' is not listed in .zenit.toml. "
            "If you removed it manually, edit .zenit.toml to reflect the current state."
        )

    # ── no other installed addon depends on this one (transitive) ─────────────
    graph = DependencyGraph.build_from_meta(available_meta)
    all_dependents = graph.dependents(addon_id) & set(lockfile.addons)
    if all_dependents:
        dep_str = ", ".join(sorted(all_dependents))
        raise ZenitError(
            f"Cannot remove '{addon_id}' - it is required by: {dep_str}. "
            f"Remove {dep_str} first."
        )

    # ── template does not require this addon ──────────────────────────────────
    if lockfile.template_source == "native":
        zenit_root = get_zenit_root()
        try:
            template_config = load_template_config(zenit_root, lockfile.template)
            if addon_id in template_config.requires_addons:
                raise ZenitError(
                    f"'{addon_id}' is required by the '{lockfile.template}' template "
                    f"and cannot be removed."
                )
        except FileNotFoundError:
            pass  # Template not found locally - skip this check

    # ── addon's own can_remove check ──────────────────────────────────────────
    cfg = get_addon(addon_id)
    hooks = cfg._module
    if hooks is not None and hooks.can_remove is not None:
        reason = hooks.can_remove(project_dir, lockfile)
        if reason:
            raise ZenitError(reason)

    return lockfile
