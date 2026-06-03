"""Project inventory scanning for env vars, compose services, and dependencies."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from zenit.core._filenames import COMPOSE_FILE, ENV_FILES, PYPROJECT_FILE
from zenit.core.manifest import dep_package_name


def _inventory_env(project_dir: Path) -> list[str]:
    keys: list[str] = []
    for fname in ENV_FILES:
        path = project_dir / fname
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key = line.split("=", 1)[0].strip()
                if key:
                    keys.append(key)
    return keys


def _inventory_compose(project_dir: Path) -> tuple[list[str], list[str]]:
    compose_path = project_dir / COMPOSE_FILE
    if not compose_path.exists():
        return [], []
    try:
        data: dict[str, Any] = (
            YAML().load(compose_path.read_text(encoding="utf-8")) or {}
        )
    except Exception:
        return [], []

    services = list(data.get("services", {}).keys())
    volumes = list(data.get("volumes", {}).keys())
    return services, volumes


def _extract_poetry_deps(
    poetry_section: dict[str, object],
) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    for pkg_name, spec in poetry_section.items():
        if pkg_name == "python":
            continue
        if isinstance(spec, str):
            result.append((pkg_name, spec))
        elif isinstance(spec, dict):
            version = spec.get("version", "")
            if isinstance(version, str):
                result.append((pkg_name, version))
    return result


def _inventory_deps(project_dir: Path) -> list[tuple[str, str, bool]]:
    pyproject_path = project_dir / PYPROJECT_FILE
    if not pyproject_path.exists():
        return []
    try:
        with open(pyproject_path, "rb") as f:
            data = tomllib.load(f)
    except Exception:
        return []

    result: list[tuple[str, str, bool]] = []

    project = data.get("project", {})
    deps = project.get("dependencies", [])
    if isinstance(deps, list):
        for dep in deps:
            if isinstance(dep, str):
                pkg = dep_package_name(dep)
                result.append((pkg, dep, False))

    dep_groups = data.get("dependency-groups", {})
    if isinstance(dep_groups, dict):
        dev = dep_groups.get("dev", [])
        if isinstance(dev, list):
            for dep in dev:
                if isinstance(dep, str):
                    pkg = dep_package_name(dep)
                    result.append((pkg, dep, True))

    tool = data.get("tool", {})
    if isinstance(tool, dict):
        poetry = tool.get("poetry", {})
        if isinstance(poetry, dict):
            prod = poetry.get("dependencies", {})
            if isinstance(prod, dict):
                for pkg_name, spec in _extract_poetry_deps(prod):
                    result.append((pkg_name, spec, False))

            dev_legacy = poetry.get("dev-dependencies", {})
            if isinstance(dev_legacy, dict):
                for pkg_name, spec in _extract_poetry_deps(dev_legacy):
                    result.append((pkg_name, spec, True))

            groups = poetry.get("group", {})
            if isinstance(groups, dict):
                for group_name, group_data in groups.items():
                    if isinstance(group_data, dict):
                        group_deps = group_data.get("dependencies", {})
                        if isinstance(group_deps, dict):
                            is_dev = group_name != "main"
                            for pkg_name, spec in _extract_poetry_deps(group_deps):
                                result.append((pkg_name, spec, is_dev))

    return result
