import re
import shutil
import subprocess
import sys
from pathlib import Path

import typer

from zenit.cli.ui import error, info
from zenit.schema.models import AddonConfig


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
    except subprocess.CalledProcessError, ValueError:
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
    available: list[AddonConfig],
    template: str = "",
) -> None:
    """Abort with exit code 1 if any selected addon's requirements are missing
    or if an addon is incompatible with the selected template."""
    requires_map = {cfg.id: cfg.requires for cfg in available}
    conflicts_map = {cfg.id: cfg.conflicts_with for cfg in available}
    templates_map = {cfg.id: cfg.templates for cfg in available}

    for addon in addons:
        # Template-compatibility check.
        allowed_templates = templates_map.get(addon, [])
        if allowed_templates and template and template not in allowed_templates:
            allowed_str = ", ".join(allowed_templates)
            error(
                f"Addon '{addon}' is only compatible with the {allowed_str} template, "
                f"not '{template}'."
            )
            raise typer.Exit(1)

        # Dependency check.
        for req in requires_map.get(addon, []):
            if req not in addons:
                error(f"Addon '{addon}' requires '{req}', but it wasn't selected.")
                raise typer.Exit(1)

        # Conflict check.
        for conflict in conflicts_map.get(addon, []):
            if conflict in addons:
                error(f"Addon '{addon}' conflicts with '{conflict}'.")
                raise typer.Exit(1)
