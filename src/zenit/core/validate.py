import keyword
import re
import shutil
import subprocess
import sys
from pathlib import Path

import typer

from zenit.cli.ui import error, info
from zenit.core.dependency import DependencyGraph
from zenit.schema.models import AddonMeta, TemplateConfig


def validate_name(name: str, pkg_name: str) -> None:
    """Abort with exit code 1 if *name* is not a valid project name."""
    if Path(name).exists():
        error(f"Directory '{name}' already exists.")
        raise typer.Exit(1)

    if not re.match(r"^[a-zA-Z][a-zA-Z0-9_-]*$", name):
        error(f"Invalid project name '{name}'.")
        info(
            "Must start with a letter; only letters, numbers, hyphens, and underscores allowed."
        )
        raise typer.Exit(1)

    if pkg_name in sys.stdlib_module_names:
        error(f"'{pkg_name}' shadows a Python stdlib module.")
        info(f"Suggestion: '{name}-app'  or  'my-{name}'")
        raise typer.Exit(1)

    if keyword.iskeyword(pkg_name):
        error(f"'{pkg_name}' is a Python keyword.")
        info(f"Suggestion: '{name}-app'  or  'my-{name}'")
        raise typer.Exit(1)


def check_preflight() -> None:
    """Check that required tools are available; abort with exit code 1 if not."""
    failures: list[str] = []
    failures += _check_uv()
    failures += _check_git()

    if failures:
        print()
        for msg in failures:
            error(msg)
        print()
        raise typer.Exit(1)


def _check_uv() -> list[str]:
    if shutil.which("uv") is None:
        return [
            "'uv' is not installed or not in PATH.\n"
            "     Install: curl -LsSf https://astral.sh/uv/install.sh | sh"
        ]
    try:
        out = subprocess.run(
            ["uv", "--version"], capture_output=True, text=True, check=True
        ).stdout.strip()
        parts = out.split()
        if len(parts) >= 2:
            major, minor, *_ = (int(x) for x in parts[1].split("."))
            if (major, minor) < (0, 4):
                return [
                    f"uv {parts[1]} is too old (need >= 0.4).\n"
                    "     Upgrade: uv self update"
                ]
    except (subprocess.CalledProcessError, ValueError, IndexError):
        pass
    return []


def _check_git() -> list[str]:
    if shutil.which("git") is None:
        return [
            "'git' is not installed or not in PATH.\n"
            "     Install: https://git-scm.com/downloads\n"
        ]
    return []


def validate_addon_deps(
    addons: list[str],
    available: list[AddonMeta],
    template: str = "",
) -> None:
    """Abort with exit code 1 if any selected addon's requirements are missing
    or if an addon is incompatible with the selected template."""
    graph = DependencyGraph.build_from_meta(available)
    conflicts_map = {m.id: m.conflicts_with for m in available}
    templates_map = {m.id: m.templates for m in available}

    # Template-compatibility check (before dep check - better error messages).
    for addon in addons:
        allowed_templates = templates_map.get(addon, [])
        if allowed_templates and template and template not in allowed_templates:
            allowed_str = ", ".join(allowed_templates)
            error(
                f"Addon '{addon}' is only compatible with the {allowed_str} template, "
                f"not '{template}'."
            )
            raise typer.Exit(1)

    # Transitive dependency check (all deps of deps).
    all_required = graph.closure(set(addons))
    missing = sorted(all_required - set(addons))
    if missing:
        for dep in missing:
            consumers = graph.dependents(dep) & set(addons)
            if consumers:
                for consumer in sorted(consumers):
                    error(
                        f"Addon '{consumer}' requires '{dep}', but it wasn't selected."
                    )
            else:
                error(f"Addon '{dep}' is required but wasn't selected.")
        raise typer.Exit(1)

    # Conflict check.
    for addon in addons:
        for conflict in conflicts_map.get(addon, []):
            if conflict in addons:
                error(f"Addon '{addon}' conflicts with '{conflict}'.")
                raise typer.Exit(1)


def validate_template_requires_addons(
    template_config: TemplateConfig,
    selected_addons: list[str],
) -> None:
    """Abort with exit code 1 if the template requires addons that aren't selected."""
    missing = [
        req for req in template_config.requires_addons if req not in selected_addons
    ]
    if missing:
        error(
            f"Template '{template_config.id}' requires the following addon(s): "
            f"{', '.join(missing)}."
        )
        info(f"Re-run with: -a {' -a '.join(missing)}")
        raise typer.Exit(1)
