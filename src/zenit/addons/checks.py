"""Precondition checking for `zenit add`.

Each addon may expose a ``can_apply(project_dir, lockfile)`` function in its
``addon.py``. If present, it is called before any writes happen.

Return contract
---------------
- Return ``None`` (or don't define the function) → addon assumes it can apply.
- Return a non-empty string → human-readable reason why it cannot; the add
  command will raise ``ZenitError`` with this message and abort.

Example in an addon.py
-----------------------
    def can_apply(project_dir: Path, lockfile: ZenitLockfile) -> str | None:
        pkg_name = lockfile.template  # use lockfile to know the layout
        ...
        if (project_dir / "src").exists():
            return None
        return "No src/ directory found — this addon expects a src layout."
"""

from __future__ import annotations

from pathlib import Path

from zenit.core.lockfile import ZenitLockfile, read_lockfile
from zenit.schema.exceptions import ZenitError
from zenit.schema.models import AddonConfig


def check_can_add(
    project_dir: Path,
    addon_id: str,
    available: list[AddonConfig],
) -> ZenitLockfile:
    """Run all precondition checks for adding *addon_id* to *project_dir*.

    Returns the parsed lockfile on success (callers need it to know the
    template and currently installed addons).

    Raises ZenitError with a clear message on any failure — the caller
    just needs to print it and exit.
    """
    # ── lockfile ──────────────────────────────────────────────────────────────
    lockfile = read_lockfile(project_dir)
    if lockfile is None:
        raise ZenitError(
            "No .zenit.toml found. "
            "'zenit add' only works in projects scaffolded by zenit."
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

    # ── not already installed ─────────────────────────────────────────────────
    if addon_id in lockfile.addons:
        raise ZenitError(
            f"'{addon_id}' is already listed in .zenit.toml. "
            "If you removed it manually, edit .zenit.toml to reflect the current state."
        )

    # ── template compatibility ─────────────────────────────────────────────────
    cfg = next(c for c in available if c.id == addon_id)
    if cfg.templates and lockfile.template not in cfg.templates:
        allowed = ", ".join(cfg.templates)
        raise ZenitError(
            f"'{addon_id}' is only compatible with the {allowed} template, "
            f"but this project uses '{lockfile.template}'."
        )

    # ── dependency addons are installed ───────────────────────────────────────
    missing_deps = [r for r in cfg.requires if r not in lockfile.addons]
    if missing_deps:
        missing_str = ", ".join(missing_deps)
        raise ZenitError(
            f"'{addon_id}' requires {missing_str}. "
            f"Run 'zenit add {missing_deps[0]}' first."
        )

    # ── addon's own can_apply check ───────────────────────────────────────────
    hooks = cfg._module
    if hooks is not None and hooks.can_apply is not None:
        reason = hooks.can_apply(project_dir, lockfile)
        if reason:
            raise ZenitError(reason)

    return lockfile
