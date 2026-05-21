"""Dependency injection into an existing pyproject.toml after running zenit add.

Uses tomlkit for round-trip parsing so that the user's formatting, comments,
and ordering are preserved. Only appends — never removes or reorders existing
entries.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import cast

import tomlkit
from tomlkit.container import Container


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
    pyproject_path = project_dir / "pyproject.toml"
    if not pyproject_path.exists():
        raise FileNotFoundError(
            "pyproject.toml not found — cannot inject dependencies."
        )

    doc = tomlkit.parse(pyproject_path.read_text(encoding="utf-8"))

    added_deps: list[str] = []
    added_dev_deps: list[str] = []

    # ── runtime deps ──────────────────────────────────────────────────────────
    project_table = cast(Container, doc.get("project", {}))
    existing_deps = cast(
        list[str], project_table.get("dependencies") or tomlkit.array()
    )
    existing_names = {_pkg_name(str(d)) for d in existing_deps}

    for dep in deps:
        if _pkg_name(dep) not in existing_names:
            existing_deps.append(dep)
            existing_names.add(_pkg_name(dep))
            added_deps.append(dep)

    # ── dev deps ──────────────────────────────────────────────────────────────
    # Support both [dependency-groups] dev (PEP 735 / uv style) and
    # [project.optional-dependencies] dev.
    if "dependency-groups" in doc:
        group = cast(Container, doc["dependency-groups"])
        existing_dev = cast(list[str], group.get("dev") or tomlkit.array())
        existing_dev_names = {_pkg_name(str(d)) for d in existing_dev}
        for dep in dev_deps:
            if _pkg_name(dep) not in existing_dev_names:
                existing_dev.append(dep)
                existing_dev_names.add(_pkg_name(dep))
                added_dev_deps.append(dep)

    elif "project" in doc and "optional-dependencies" in cast(
        Container, doc["project"]
    ):
        opt = cast(Container, cast(Container, doc["project"])["optional-dependencies"])
        existing_dev = cast(list[str], opt.get("dev") or tomlkit.array())
        existing_dev_names = {_pkg_name(str(d)) for d in existing_dev}
        for dep in dev_deps:
            if _pkg_name(dep) not in existing_dev_names:
                existing_dev.append(dep)
                existing_dev_names.add(_pkg_name(dep))
                added_dev_deps.append(dep)

    pyproject_path.write_text(tomlkit.dumps(doc), encoding="utf-8")
    return added_deps, added_dev_deps


def _pkg_name(dep: str) -> str:
    """Extract the bare package name from a dependency specifier.

    Examples:
        "redis>=5"              -> "redis"
        "celery[redis]>=5"      -> "celery"
        "sentry-sdk[fastapi]"   -> "sentry-sdk"
        "fakeredis[aioredis]"   -> "fakeredis"
    """
    match = re.match(r"^([a-zA-Z0-9_.-]+)", dep)
    return match.group(1).lower() if match else dep.lower()
