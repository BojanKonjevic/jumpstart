"""Export addon/template data for the studio page.

Generates ``studio-data.json`` — consumed by ``studio.html``.
Runnable via: uv run python scripts/export-configure-data.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import zenit
from zenit.addons._registry import get_addon, list_addons
from zenit.core._filenames import COMMON_FILES
from zenit.templates._load_config import list_templates, load_template_config

_HERE = Path(__file__).parent.absolute()
_PROJECT_ROOT = _HERE.parent
ZENIT_ROOT = Path(zenit.__file__).parent.absolute()

ADDON_TAGS: dict[str, list[str]] = {
    "postgres": ["database"],
    "redis": ["database"],
    "sqlalchemy": ["database"],
    "sqlmodel": ["database"],
    "docker": ["infra"],
    "celery": ["infra"],
    "sentry": ["ops"],
    "github-actions": ["ci"],
    "auth-manual": ["auth"],
}

CAT_LABELS: dict[str, str] = {
    "database": "Database",
    "infra": "Infrastructure",
    "auth": "Auth",
    "ops": "Operations",
    "ci": "CI/CD",
}

CAT_COLORS: dict[str, str] = {
    "database": "#78a8c2",
    "infra": "#9c9080",
    "auth": "#c8922e",
    "ops": "#b87878",
    "ci": "#7aaa72",
}

PIPELINE_STEPS: list[dict[str, str]] = [
    {"id": "template", "label": "template files"},
    {"id": "addon-files", "label": "addon files"},
    {"id": "injections", "label": "injections"},
    {"id": "deps", "label": "dependencies"},
    {"id": "env", "label": "env vars"},
    {"id": "recipes", "label": "just recipes"},
    {"id": "compose", "label": "compose merge"},
    {"id": "manifest", "label": "manifest"},
    {"id": "git", "label": "git init"},
]

MAX_STEP = len(PIPELINE_STEPS)

_RECIPE_LINE_RE = re.compile(r"^(@?[a-zA-Z0-9_-]+)(?:\s+[^:]+)?:")


def _extract_recipe_names(text: str) -> list[str]:
    names: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or raw_line[0] in (" ", "\t"):
            continue
        m = _RECIPE_LINE_RE.match(line)
        if m:
            names.append(m.group(1).lstrip("@"))
    return names


def _injection_summary(content: str) -> str:
    text = re.sub(r"\[%.*?%\]", "", content)
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("if ", "for ", "while ", "with ", "#", "[%")):
            continue
        for kw in ("await ", "return "):
            if line.startswith(kw):
                line = line[len(kw) :]
        if line.startswith("from ") and " import " in line:
            parts = line.split(" import ")
            return parts[-1].split(",")[0].strip().lstrip(".")
        if line.startswith("import "):
            return line[7:].split(",")[0].strip()
        m = re.match(r"^[^a-zA-Z_]*([a-zA-Z_]\w*(?:\.\w+)*(?:\(\))?)", line)
        if m:
            return m.group(1)
    return ""


def _extract_env_var_keys(env_vars: list) -> list[str]:
    from zenit.schema.models import EnvVar

    if not env_vars:
        return []
    keys: list[str] = []
    for ev in env_vars:
        if isinstance(ev, EnvVar):
            keys.append(ev.key)
    return keys


def _extract_file_dests(files: list) -> list[str]:
    from zenit.schema.models import FileContribution

    if not files:
        return []
    dests: list[str] = []
    for fc in files:
        if isinstance(fc, FileContribution):
            dests.append(fc.dest.replace("{{pkg_name}}", "((pkg_name))"))
    return dests


def _format_injections(injections: list) -> list[str]:
    from zenit.schema.models import Injection

    if not injections:
        return []
    result: list[str] = []
    for inj in injections:
        if isinstance(inj, Injection):
            summary = _injection_summary(inj.content)
            if summary:
                result.append(f"{inj.point} → {summary}")
    return result


def _extract_compose_service_names(services: list) -> list[str]:
    from zenit.schema.models import ComposeService

    if not services:
        return []
    names: list[str] = []
    for svc in services:
        if isinstance(svc, ComposeService):
            names.append(svc.name)
    return names


def build_addon_data() -> list[dict]:
    """Iterate all addons, extracting full config for the configure page."""
    metas = list_addons()
    addon_list: list[dict] = []

    tag_map = ADDON_TAGS
    cat_colors = CAT_COLORS

    for meta in metas:
        cfg = get_addon(meta.id)

        tags = tag_map.get(cfg.id, [])
        first_tag = tags[0] if tags else ""
        col = cat_colors.get(first_tag, "#6e6458")

        recipe_names: list[str] = []
        for recipe_text in cfg.just_recipes:
            recipe_names.extend(_extract_recipe_names(recipe_text))

        addon_list.append(
            {
                "id": cfg.id,
                "name": cfg.id,
                "desc": cfg.description,
                "tags": tags,
                "requires": list(cfg.requires),
                "conflicts": list(cfg.conflicts_with),
                "templates": list(cfg.templates) or ["fastapi", "blank"],
                "col": col,
                "files": _extract_file_dests(cfg.files),
                "envVars": _extract_env_var_keys(cfg.env_vars),
                "deps": list(cfg.deps),
                "devDeps": list(cfg.dev_deps),
                "composeServices": _extract_compose_service_names(cfg.compose_services),
                "recipes": recipe_names,
                "injections": _format_injections(cfg.injections),
            }
        )

    return addon_list


def build_template_data() -> dict:
    """Iterate all templates, extracting config + common files."""
    metas = list_templates()
    templates_list: list[dict] = []
    template_files: dict[str, list[str]] = {}

    common_files = list(COMMON_FILES) + [".envrc"]

    for meta in metas:
        cfg = load_template_config(ZENIT_ROOT, meta.id)

        templates_list.append(
            {
                "id": cfg.id,
                "name": cfg.id,
                "desc": f"{cfg.id}: {cfg.description}",
            }
        )

        own_files = _extract_file_dests(cfg.files)
        template_files[cfg.id] = common_files + own_files

    return {"templates": templates_list, "templateFiles": template_files}


def build_json() -> str:
    addon_data = build_addon_data()
    template_data = build_template_data()

    from importlib.metadata import version

    ver = version("zenit")

    payload = {
        "version": ver,
        "templates": template_data["templates"],
        "addons": addon_data,
        "catLabels": CAT_LABELS,
        "catColors": CAT_COLORS,
        "templateFiles": template_data["templateFiles"],
        "pipelineSteps": PIPELINE_STEPS,
        "maxStep": MAX_STEP,
    }

    return json.dumps(payload, indent=2, ensure_ascii=False)


def main() -> None:
    output_path = _PROJECT_ROOT / "studio-data.json"
    data = build_json()
    output_path.write_text(data, encoding="utf-8")
    print(f"Wrote {output_path} ({output_path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
