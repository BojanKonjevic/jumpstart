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
    schema_version = 4

All fields are optional when reading — the lockfile may be absent (project
was not scaffolded by zenit, or was scaffolded before lockfiles existed).
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from importlib.metadata import version as get_version
from pathlib import Path
from typing import TYPE_CHECKING

import tomlkit
import tomlkit.items

from zenit.core._filenames import LOCKFILE_NAME
from zenit.core.filesystem import atomic_write_text

if TYPE_CHECKING:
    from zenit.schema.models import Manifest

SCHEMA_VERSION = 4
VALID_TEMPLATE_SOURCES: frozenset[str] = frozenset({"native", "copier"})


@dataclass
class ZenitLockfile:
    template: str = ""
    addons: list[str] = field(default_factory=list)
    zenit_version: str = ""
    schema_version: int = 0
    template_source: str = "native"  # "native" | "copier"
    template_uri: str = ""
    template_has_tasks: bool = False
    template_file_paths: list[str] = field(default_factory=list)


def _build_project_table(
    template: str,
    addons: list[str],
    template_source: str = "native",
    template_uri: str = "",
    template_has_tasks: bool = False,
    template_file_paths: list[str] | None = None,
) -> tomlkit.items.Table:
    """Build a ``[project]`` table with the standard fields."""
    try:
        zenit_version = get_version("zenit")
    except Exception:
        zenit_version = "dev"

    table = tomlkit.table()
    table.add("template", template)
    table.add("addons", list(addons))
    table.add("zenit_version", zenit_version)
    table.add("schema_version", SCHEMA_VERSION)
    if template_source != "native":
        table.add("template_source", template_source)
    if template_uri:
        table.add("template_uri", template_uri)
    if template_has_tasks:
        table.add("template_has_tasks", template_has_tasks)
    if template_file_paths:
        arr = tomlkit.array()
        arr.multiline(True)
        for p in template_file_paths:
            arr.append(p)
        table.add("template_file_paths", arr)
    return table


def write_lockfile(
    project_dir: Path,
    template: str,
    addons: list[str],
    *,
    template_source: str = "native",
    template_uri: str = "",
    template_has_tasks: bool = False,
    template_file_paths: list[str] | None = None,
) -> None:
    """Write the [project] section of .zenit.toml into *project_dir*.

    Uses tomlkit round-trip so any other sections already in the file
    (e.g. [manifest]) are preserved exactly.
    """
    write_zenit_toml(
        project_dir,
        template=template,
        addons=addons,
        template_source=template_source,
        template_uri=template_uri,
        template_has_tasks=template_has_tasks,
        template_file_paths=template_file_paths,
    )


def write_zenit_toml(
    project_dir: Path,
    *,
    template: str | None = None,
    addons: list[str] | None = None,
    template_source: str = "native",
    template_uri: str = "",
    template_has_tasks: bool = False,
    template_file_paths: list[str] | None = None,
    manifest: Manifest | None = None,
) -> None:
    """Single atomic write of both ``[project]`` and ``[manifest]`` sections.

    Reads ``.zenit.toml`` once (or creates an empty document), updates
    whichever section(s) are provided, and writes back atomically.

    When *template* is ``None`` the ``[project]`` section is left unchanged.
    When *manifest* is ``None`` the ``[manifest]`` section is left unchanged.
    When both are provided both sections are updated in a single write —
    eliminating the inconsistency window of two sequential writes.
    """
    path = project_dir / LOCKFILE_NAME
    doc = (
        tomlkit.parse(path.read_text(encoding="utf-8"))
        if path.exists()
        else tomlkit.document()
    )

    if template is not None:
        doc["project"] = _build_project_table(
            template,
            addons or [],
            template_source=template_source,
            template_uri=template_uri,
            template_has_tasks=template_has_tasks,
            template_file_paths=template_file_paths,
        )
        doc.pop("migrated", None)

    if manifest is not None:
        from zenit.core.manifest import encode_manifest

        doc["manifest"] = encode_manifest(manifest)

    atomic_write_text(path, tomlkit.dumps(doc))


def _upgrade_legacy_lockfile(
    project: dict[str, object],
    data: dict[str, object],
) -> dict[str, object]:
    """Upgrade a legacy lockfile (v3 or earlier) to the v4 format in-memory.

    Returns the upgraded *project* dict with new fields populated.
    """
    upgraded = dict(project)

    legacy_template = str(upgraded.get("template", ""))

    # Detect "migrated:" prefix → strip and set copier source
    if legacy_template.startswith("migrated:"):
        upgraded["template"] = legacy_template[len("migrated:") :]
        upgraded["template_source"] = "copier"

    # Detect [migrated] section → convert to flat fields
    migrated_raw = data.get("migrated")
    if isinstance(migrated_raw, dict):
        upgraded["template_source"] = "copier"
        if not upgraded.get("template_uri"):
            upgraded["template_uri"] = str(migrated_raw.get("source", ""))
        upgraded["template_has_tasks"] = bool(migrated_raw.get("has_tasks", False))
        if not upgraded.get("template_file_paths"):
            upgraded["template_file_paths"] = [
                p for p in migrated_raw.get("file_paths", []) if isinstance(p, str)
            ]

    return upgraded


def read_lockfile(project_dir: Path) -> ZenitLockfile | None:
    """Read .zenit.toml from *project_dir*.

    Returns None if the file does not exist or cannot be parsed — callers
    must handle the absent-lockfile case gracefully.

    Legacy lockfiles (v3 and earlier) are auto-upgraded in memory on read.
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

    # Auto-upgrade legacy lockfiles in memory
    project = _upgrade_legacy_lockfile(project, data)

    template = project.get("template", "")
    addons = project.get("addons", [])
    zenit_version = project.get("zenit_version", "")
    schema_version = project.get("schema_version", 0)
    template_source = project.get("template_source", "native")
    template_uri = project.get("template_uri", "")
    template_has_tasks = project.get("template_has_tasks", False)
    template_file_paths = project.get("template_file_paths", [])

    if not isinstance(template, str):
        template = ""
    if not isinstance(addons, list):
        addons = []
    addons = [a for a in addons if isinstance(a, str)]
    if not isinstance(zenit_version, str):
        zenit_version = ""
    if not isinstance(schema_version, int):
        schema_version = 0
    if (
        not isinstance(template_source, str)
        or template_source not in VALID_TEMPLATE_SOURCES
    ):
        template_source = "native"
    if not isinstance(template_uri, str):
        template_uri = ""
    if not isinstance(template_has_tasks, bool):
        template_has_tasks = False
    if not isinstance(template_file_paths, list):
        template_file_paths = []
    template_file_paths = [p for p in template_file_paths if isinstance(p, str)]

    return ZenitLockfile(
        template=template,
        addons=addons,
        zenit_version=zenit_version,
        schema_version=schema_version,
        template_source=template_source,
        template_uri=template_uri,
        template_has_tasks=template_has_tasks,
        template_file_paths=template_file_paths,
    )
