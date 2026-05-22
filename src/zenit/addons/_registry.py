"""Addon registry — discovers ``addon.py`` files and returns ``AddonConfig`` objects."""

import functools
import importlib.util
from pathlib import Path

from zenit.schema.models import AddonConfig, AddonHooks

_HERE = Path(__file__).parent.absolute()


@functools.cache
def get_available_addons() -> list[AddonConfig]:
    """Return one ``AddonConfig`` for every addon directory found under this package."""
    addons: list[AddonConfig] = []
    for addon_dir in sorted(
        p for p in _HERE.iterdir() if p.is_dir() and not p.name.startswith("_")
    ):
        addon_py = addon_dir / "addon.py"
        if not addon_py.exists():
            continue
        spec = importlib.util.spec_from_file_location("addon_config", addon_py)
        mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        spec.loader.exec_module(mod)  # type: ignore[union-attr]

        cfg: AddonConfig = mod.config
        hooks = AddonHooks(
            post_apply=getattr(mod, "post_apply", None),
            health_check=getattr(mod, "health_check", None),
            can_apply=getattr(mod, "can_apply", None),
            can_remove=getattr(mod, "can_remove", None),
        )
        cfg._module = hooks
        addons.append(cfg)
    return addons
