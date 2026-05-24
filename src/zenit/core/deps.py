"""Dependency injection into an existing pyproject.toml after running zenit add.

Uses tomlkit for round-trip parsing so that the user's formatting, comments,
and ordering are preserved. Only appends — never removes or reorders existing
entries.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

import tomlkit
from tomlkit.container import Container

from zenit.core._filenames import PYPROJECT_FILE
from zenit.core.manifest import _dep_package_name


def _add_deps_if_missing(
    target_list: list[str],
    existing_names: set[str],
    deps_to_add: list[str],
) -> list[str]:
    added: list[str] = []
    for dep in deps_to_add:
        if _dep_package_name(dep) not in existing_names:
            target_list.append(dep)
            existing_names.add(_dep_package_name(dep))
            added.append(dep)
    return added


def inject_deps(
    project_dir: Path,
    deps: list[str],
    dev_deps: list[str],
) -> tuple[list[str], list[str]]:
    """Append missing deps into pyproject.toml.

    Returns (added_deps, added_dev_deps) — the deps that were actually written.
    Deps that are already present (by package name, ignoring version specifiers)
    are skipped silently.
    """
    pyproject_path = project_dir / PYPROJECT_FILE
    if not pyproject_path.exists():
        raise FileNotFoundError(
            "pyproject.toml not found — cannot inject dependencies."
        )

    doc = tomlkit.parse(pyproject_path.read_text(encoding="utf-8"))

    # ── runtime deps ──────────────────────────────────────────────────────────
    project_table = cast(Container, doc.get("project", {}))
    existing_deps = cast(
        list[str], project_table.get("dependencies") or tomlkit.array()
    )
    existing_names = {_dep_package_name(str(d)) for d in existing_deps}

    added_deps = _add_deps_if_missing(existing_deps, existing_names, deps)

    # ── dev deps ──────────────────────────────────────────────────────────────
    # Support both [dependency-groups] dev (PEP 735 / uv style) and
    # [project.optional-dependencies] dev.
    if "dependency-groups" in doc:
        group = cast(Container, doc["dependency-groups"])
        existing_dev = cast(list[str], group.get("dev") or tomlkit.array())
        existing_dev_names = {_dep_package_name(str(d)) for d in existing_dev}
        added_dev_deps = _add_deps_if_missing(
            existing_dev, existing_dev_names, dev_deps
        )

    elif "project" in doc and "optional-dependencies" in cast(
        Container, doc["project"]
    ):
        opt = cast(Container, cast(Container, doc["project"])["optional-dependencies"])
        existing_dev = cast(list[str], opt.get("dev") or tomlkit.array())
        existing_dev_names = {_dep_package_name(str(d)) for d in existing_dev}
        added_dev_deps = _add_deps_if_missing(
            existing_dev, existing_dev_names, dev_deps
        )

    else:
        added_dev_deps = []

    pyproject_path.write_text(tomlkit.dumps(doc), encoding="utf-8")
    return added_deps, added_dev_deps
