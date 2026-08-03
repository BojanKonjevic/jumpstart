"""Dependency injection into an existing pyproject.toml after running zenit add.

Uses tomlkit for round-trip parsing so that the user's formatting, comments,
and ordering are preserved. Only appends - never removes or reorders existing
entries.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

import tomlkit
from tomlkit.container import Container

from zenit.core._filenames import PYPROJECT_FILE
from zenit.core.filesystem import atomic_write_text
from zenit.core.manifest import dep_package_name


def _add_deps_if_missing(
    target_list: list[str],
    existing_names: set[str],
    deps_to_add: list[str],
) -> list[str]:
    added: list[str] = []
    for dep in deps_to_add:
        if dep_package_name(dep) not in existing_names:
            target_list.append(dep)
            existing_names.add(dep_package_name(dep))
            added.append(dep)
    return added


def _resolve_dev_target(
    doc: tomlkit.TOMLDocument,
) -> tuple[list[str], set[str]] | None:
    """Find the dev-dependency list in either ``[dependency-groups]`` or
    ``[project.optional-dependencies]``. Returns ``(list, existing_names)``
    or ``None`` if neither section exists."""
    if "dependency-groups" in doc:
        group = cast(Container, doc["dependency-groups"])
        existing_dev = group.get("dev")
        if existing_dev is None:
            existing_dev = tomlkit.array()
            group["dev"] = existing_dev
        existing_dev = cast(list[str], existing_dev)
        existing_names = {dep_package_name(str(d)) for d in existing_dev}
        return existing_dev, existing_names

    if "project" in doc and "optional-dependencies" in cast(Container, doc["project"]):
        opt = cast(Container, cast(Container, doc["project"])["optional-dependencies"])
        existing_dev = opt.get("dev")
        if existing_dev is None:
            existing_dev = tomlkit.array()
            opt["dev"] = existing_dev
        existing_dev = cast(list[str], existing_dev)
        existing_names = {dep_package_name(str(d)) for d in existing_dev}
        return existing_dev, existing_names

    return None


def inject_deps(
    project_dir: Path,
    deps: list[str],
    dev_deps: list[str],
) -> tuple[list[str], list[str]]:
    """Append missing deps into pyproject.toml.

    Returns (added_deps, added_dev_deps) - the deps that were actually written.
    Deps that are already present (by package name, ignoring version specifiers)
    are skipped silently.
    """
    pyproject_path = project_dir / PYPROJECT_FILE
    if not pyproject_path.exists():
        raise FileNotFoundError(
            "pyproject.toml not found - cannot inject dependencies."
        )

    doc = tomlkit.parse(pyproject_path.read_text(encoding="utf-8"))

    # ── runtime deps ──────────────────────────────────────────────────────────
    # Ensure [project] table exists so our array stays linked to the document.
    project_table = doc.get("project")
    if project_table is None:
        project_table = tomlkit.table()
        doc["project"] = project_table
    project_table = cast(Container, project_table)

    existing_deps = project_table.get("dependencies")
    if existing_deps is None:
        existing_deps = tomlkit.array()
        project_table["dependencies"] = existing_deps
    existing_deps = cast(list[str], existing_deps)

    existing_names = {dep_package_name(str(d)) for d in existing_deps}
    added_deps = _add_deps_if_missing(existing_deps, existing_names, deps)

    # ── dev deps ──────────────────────────────────────────────────────────────
    # Support both [dependency-groups] dev (PEP 735 / uv style) and
    # [project.optional-dependencies] dev.
    dev_target = _resolve_dev_target(doc)
    if dev_target is not None:
        existing_dev, existing_dev_names = dev_target
        added_dev_deps = _add_deps_if_missing(
            existing_dev, existing_dev_names, dev_deps
        )
    else:
        added_dev_deps = []

    atomic_write_text(pyproject_path, tomlkit.dumps(doc))
    return added_deps, added_dev_deps
