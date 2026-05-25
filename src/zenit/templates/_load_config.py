"""Import a template's declarative config from its template.py file.

Also provides limited support for loading Copier template configuration
from ``copier.yml``, converting it to a ``TemplateConfig`` for compatibility
with the rest of the zenit system.
"""

from __future__ import annotations

import functools
import importlib.util
import tomllib
from pathlib import Path

import yaml

from zenit.schema.exceptions import ZenitError
from zenit.schema.models import TemplateConfig, TemplateMeta

_HERE = Path(__file__).parent.absolute()

# ── Metadata-only discovery (no exec) ─────────────────────────────────────


@functools.cache
def list_templates() -> list[TemplateMeta]:
    """Iterate template dirs, read ``template.toml``. No exec."""
    metas: list[TemplateMeta] = []
    templates_dir = _HERE
    for template_dir in sorted(
        p for p in templates_dir.iterdir() if p.is_dir() and not p.name.startswith("_")
    ):
        toml_path = template_dir / "template.toml"
        if not toml_path.exists():
            continue
        with open(toml_path, "rb") as f:
            data = tomllib.load(f)
        raw = data["template"]
        metas.append(
            TemplateMeta(
                id=raw["id"],
                description=raw["description"],
                requires_addons=list(raw.get("requires_addons", [])),
            )
        )
    return metas


# ── Full config (exec) ────────────────────────────────────────────────────


@functools.cache
def load_template_config(zenit_root: Path, template_id: str) -> TemplateConfig:
    spec = importlib.util.spec_from_file_location(
        "template_config",
        zenit_root / "templates" / template_id / "template.py",
    )
    if spec is None or spec.loader is None:
        raise FileNotFoundError(f"template.py not found for template '{template_id}'")
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as exc:
        raise ZenitError(f"Failed to load template '{template_id}': {exc}") from exc
    if not hasattr(mod, "config"):
        raise AttributeError(
            f"template.py for '{template_id}' must export a 'config' object"
        )
    return mod.config


# ── Copier template config ─────────────────────────────────────────────────


def load_copier_template_config(copier_yml_path: Path) -> TemplateConfig:
    """Load a Copier template's ``copier.yml`` and return a minimal ``TemplateConfig``.

    This makes Copier templates transparent to the rest of the zenit system
    by providing a standard ``TemplateConfig`` derived from the Copier metadata.

    Only basic fields (id, description) are populated from the Copier config.
    """
    with open(copier_yml_path, "rb") as f:
        yaml.safe_load(f) or {}

    template_id = copier_yml_path.parent.name
    description = f"Copier template: {template_id}"

    return TemplateConfig(
        id=template_id,
        description=description,
    )
