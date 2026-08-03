"""Addon registry - lazy-loading metadata (TOML) and on‑demand full config (exec)."""

from __future__ import annotations

import dataclasses
import functools
import importlib.util
import tomllib
from pathlib import Path

from zenit.schema.exceptions import ZenitError
from zenit.schema.models import AddonConfig, AddonHooks, AddonMeta

_HERE = Path(__file__).parent.absolute()


# ── Metadata-only discovery (no exec) ─────────────────────────────────────


@functools.cache
def list_addons() -> list[AddonMeta]:
    """Iterate addon dirs, read ``addon.toml``. No imports, no exec."""
    metas: list[AddonMeta] = []
    for addon_dir in sorted(
        p for p in _HERE.iterdir() if p.is_dir() and not p.name.startswith("_")
    ):
        toml_path = addon_dir / "addon.toml"
        if not toml_path.exists():
            continue
        with open(toml_path, "rb") as f:
            data = tomllib.load(f)
        raw = data["addon"]
        metas.append(
            AddonMeta(
                id=raw["id"],
                description=raw["description"],
                requires=list(raw.get("requires", [])),
                conflicts_with=list(raw.get("conflicts_with", [])),
                templates=list(raw.get("templates", [])),
            )
        )
    return metas


# ── On-demand full config (exec) ─────────────────────────────────────────


@functools.cache
def get_addon(addon_id: str) -> AddonConfig:
    """Exec ``addon.py`` for a single addon. Cached after first call."""
    addon_dir = _HERE / addon_id
    addon_py = addon_dir / "addon.py"
    if not addon_py.exists():
        raise FileNotFoundError(f"addon.py not found for '{addon_id}'")
    spec = importlib.util.spec_from_file_location(f"addon_config_{addon_id}", addon_py)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    try:
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
    except Exception as exc:
        raise ZenitError(f"Failed to load addon '{addon_id}': {exc}") from exc
    cfg: AddonConfig = mod.config
    hooks = AddonHooks(
        post_apply=getattr(mod, "post_apply", None),
        health_check=getattr(mod, "health_check", None),
        can_apply=getattr(mod, "can_apply", None),
        can_remove=getattr(mod, "can_remove", None),
    )
    return dataclasses.replace(cfg, _module=hooks)
