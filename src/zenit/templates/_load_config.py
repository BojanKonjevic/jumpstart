"""Import a template's declarative config from its template.py file."""

import functools
import importlib.util
from pathlib import Path

from zenit.schema.models import TemplateConfig


@functools.cache
def load_template_config(zenit_root: Path, template_id: str) -> TemplateConfig:
    spec = importlib.util.spec_from_file_location(
        "template_config",
        zenit_root / "templates" / template_id / "template.py",
    )
    if spec is None or spec.loader is None:
        raise FileNotFoundError(f"template.py not found for template '{template_id}'")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not hasattr(mod, "config"):
        raise AttributeError(
            f"template.py for '{template_id}' must export a 'config' object"
        )
    return mod.config
