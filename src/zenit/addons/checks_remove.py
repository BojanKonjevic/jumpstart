"""Precondition checking for `zenit remove`.

Each addon may expose a ``can_remove(project_dir, lockfile)`` function in its
``addon.py``. If present, it is called before any writes happen.

Return contract
---------------
- Return ``None`` (or don't define the function) → addon assumes it can be removed.
- Return a non-empty string → human-readable reason why it cannot; the remove
  command will raise ``ZenitError`` with this message and abort.

Example in an addon.py
-----------------------
    def can_remove(project_dir: Path, lockfile: ZenitLockfile) -> str | None:
        if some_other_addon_depends_on_this(lockfile):
            return "Another installed addon depends on this one."
        return None
"""

from __future__ import annotations

from pathlib import Path

from zenit.core._paths import get_zenit_root
from zenit.core.lockfile import ZenitLockfile, read_lockfile
from zenit.schema.exceptions import ZenitError
from zenit.schema.models import AddonConfig
from zenit.templates._load_config import load_template_config


def check_can_remove(
    project_dir: Path,
    addon_id: str,
    available: list[AddonConfig],
) -> ZenitLockfile:
    """Run all precondition checks for removing *addon_id* from *project_dir*.

    Returns the parsed lockfile on success (callers need it to know the
    template and currently installed addons).

    Raises ZenitError with a clear message on any failure.
    """
    # ── lockfile ──────────────────────────────────────────────────────────────
    lockfile = read_lockfile(project_dir)
    if lockfile is None:
        raise ZenitError(
            "No .zenit.toml found. "
            "'zenit remove' only works in projects scaffolded by zenit."
        )
    if not lockfile.template:
        raise ZenitError(
            ".zenit.toml exists but has no template field — it may be corrupt."
        )

    # ── addon exists ──────────────────────────────────────────────────────────
    addon_ids = {cfg.id for cfg in available}
    if addon_id not in addon_ids:
        known = ", ".join(sorted(addon_ids))
        raise ZenitError(f"Unknown addon '{addon_id}'. Available addons: {known}")

    # ── is actually installed ─────────────────────────────────────────────────
    if addon_id not in lockfile.addons:
        raise ZenitError(
            f"'{addon_id}' is not listed in .zenit.toml. "
            "If you removed it manually, edit .zenit.toml to reflect the current state."
        )

    # ── no other installed addon depends on this one ──────────────────────────
    requires_map = {cfg.id: cfg.requires for cfg in available}
    dependents = [
        other_id
        for other_id in lockfile.addons
        if other_id != addon_id and addon_id in requires_map.get(other_id, [])
    ]
    if dependents:
        dep_str = ", ".join(dependents)
        raise ZenitError(
            f"Cannot remove '{addon_id}' — it is required by: {dep_str}. "
            f"Remove {dep_str} first."
        )

    # ── template does not require this addon ──────────────────────────────────

    zenit_root = get_zenit_root()
    try:
        template_config = load_template_config(zenit_root, lockfile.template)
        if addon_id in template_config.requires_addons:
            raise ZenitError(
                f"'{addon_id}' is required by the '{lockfile.template}' template "
                f"and cannot be removed."
            )
    except FileNotFoundError:
        pass  # Template not found locally — skip this check

    # ── addon's own can_remove check ──────────────────────────────────────────
    cfg = next(c for c in available if c.id == addon_id)
    hooks = cfg._module
    if hooks is not None and hooks.can_remove is not None:
        reason = hooks.can_remove(project_dir, lockfile)
        if reason:
            raise ZenitError(reason)

    return lockfile
