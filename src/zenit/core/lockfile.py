"""zenit project lockfile — .zenit.toml

Written into the project root at scaffold time. Read by `zenit add` to know
what template and addons are already present, and what version of zenit
created the project.

Format
------
    [project]
    template = "fastapi"
    addons = ["redis"]
    zenit_version = "1.0.1"
    schema_version = 2

All fields are optional when reading — the lockfile may be absent (project
was not scaffolded by zenit, or was scaffolded before lockfiles existed).
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from importlib.metadata import version as get_version
from pathlib import Path

import tomlkit

from zenit.core._filenames import LOCKFILE_NAME
from zenit.core.filesystem import atomic_write_text

# NOTE: SCHEMA_VERSION is written to disk as the schema_version field in the
# [project] section of .zenit.toml.  It gates the on-disk project-structure
# contract: if a project file's stored value doesn't match this constant,
# doctor warns the user.  It is intentionally separate from
# MANIFEST_SCHEMA_VERSION in manifest.py, which gates fingerprint
# normalisation — those are independent events that should not be coupled.
SCHEMA_VERSION = 3


@dataclass
class MigratedMeta:
    """Metadata about a Copier template migration stored in ``[migrated]``."""

    source: str  # original URL or local path
    has_tasks: bool  # whether _tasks were present in copier.yml
    file_paths: list[str] = field(default_factory=list)  # all file paths written


@dataclass
class ZenitLockfile:
    template: str = ""
    addons: list[str] = field(default_factory=list)
    zenit_version: str = ""
    schema_version: int = 0
    migrated: MigratedMeta | None = None  # None for non-migrated projects


def write_lockfile(
    project_dir: Path,
    template: str,
    addons: list[str],
    migrated: MigratedMeta | None = None,
) -> None:
    """Write the [project] section of .zenit.toml into *project_dir*.

    Uses tomlkit round-trip so any other sections already in the file
    (e.g. [manifest]) are preserved exactly.

    If *migrated* is not None, a ``[migrated]`` section is also written.
    """
    try:
        zenit_version = get_version("zenit")
    except Exception:
        zenit_version = "dev"

    path = project_dir / LOCKFILE_NAME
    doc = (
        tomlkit.parse(path.read_text(encoding="utf-8"))
        if path.exists()
        else tomlkit.document()
    )

    project = tomlkit.table()
    project.add("template", template)
    project.add("addons", list(addons))
    project.add("zenit_version", zenit_version)
    project.add("schema_version", SCHEMA_VERSION)
    doc["project"] = project

    if migrated is not None:
        mig = tomlkit.table()
        mig.add("source", migrated.source)
        mig.add("has_tasks", migrated.has_tasks)
        file_paths = tomlkit.array()
        file_paths.multiline(True)
        for p in migrated.file_paths:
            file_paths.append(p)
        mig.add("file_paths", file_paths)
        doc["migrated"] = mig

    atomic_write_text(path, tomlkit.dumps(doc))


def read_lockfile(project_dir: Path) -> ZenitLockfile | None:
    """Read .zenit.toml from *project_dir*.

    Returns None if the file does not exist or cannot be parsed — callers
    must handle the absent-lockfile case gracefully.
    """
    path = project_dir / LOCKFILE_NAME
    if not path.exists():
        return None

    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except Exception:
        return None

    project = data.get("project", {})
    if not isinstance(project, dict):
        return None

    template = project.get("template", "")
    addons = project.get("addons", [])
    zenit_version = project.get("zenit_version", "")
    schema_version = project.get("schema_version", 0)

    if not isinstance(template, str):
        template = ""
    if not isinstance(addons, list):
        addons = []
    addons = [a for a in addons if isinstance(a, str)]
    if not isinstance(zenit_version, str):
        zenit_version = ""
    if not isinstance(schema_version, int):
        schema_version = 0

    migrated: MigratedMeta | None = None
    migrated_raw = data.get("migrated")
    if isinstance(migrated_raw, dict):
        migrated = MigratedMeta(
            source=str(migrated_raw.get("source", "")),
            has_tasks=bool(migrated_raw.get("has_tasks", False)),
            file_paths=[
                p for p in migrated_raw.get("file_paths", []) if isinstance(p, str)
            ],
        )

    return ZenitLockfile(
        template=template,
        addons=addons,
        zenit_version=zenit_version,
        schema_version=schema_version,
        migrated=migrated,
    )
