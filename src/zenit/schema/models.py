"""Declarative addon/template contribution types — no file I/O here."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from zenit.core.context import Context
    from zenit.core.filesystem import FileSystem
    from zenit.core.lockfile import ZenitLockfile
    from zenit.doctor.doctor import HealthIssue

from zenit.core.recipes import RecipeCollection

# ── Injection point declaration (template side) ───────────────────────────────


@dataclass
class LocatorSpec:
    """A structural description of where to insert code in a Python file.

    ``name`` must match a function exported from ``core/handlers/locators.py``.
    ``args`` are passed as keyword arguments to that function.
    """

    name: str
    args: dict[str, Any] = field(default_factory=dict)


@dataclass
class InjectionPoint:
    """A named location inside a generated file where addons can inject code.

    ``file`` is a path relative to the project root; it may contain
    ``{{pkg_name}}`` which is resolved at apply time.

    ``locator`` drives structural injection for Python files.  For non-Python
    files the locator is unused — handlers locate insertion points by file type
    semantics (append for .env, merge for .yml, etc.).
    """

    file: str
    locator: LocatorSpec


class EntrySource(StrEnum):
    """Ownership source for manifest entries."""

    TEMPLATE = "template"
    ADDON = "addon"


# ── Manifest data types (.zenit.toml [manifest] section) ─────────────────────


@dataclass
class ManifestBlock:
    """Record of a single Python code injection."""

    addon: str
    point: str
    file: str  # resolved path (pkg_name substituted)
    lines: str  # "start-end", 1-based inclusive
    fingerprint: str  # sha256 of canonical libcst output
    fingerprint_normalised: str  # sha256 of normalised output (formatter-resilient)
    locator: LocatorSpec


@dataclass
class EnvEntry:
    """Ownership record for a single environment variable."""

    key: str
    source: EntrySource
    addon: str  # "" for template-owned


@dataclass
class OwnedEntry:
    """Ownership record for a compose service, volume, or just recipe."""

    name: str
    source: EntrySource
    addon: str  # "" for template-owned


@dataclass
class DependencyEntry:
    """Ownership record for a pyproject.toml dependency."""

    package: str
    spec: str  # e.g. "redis>=5"
    source: EntrySource
    addon: str  # "" for template-owned
    dev: bool


@dataclass
class Manifest:
    """Full manifest of all zenit-managed content in a project.

    Written at scaffold time; updated by every ``zenit add`` and
    ``zenit remove``.  Read by ``zenit doctor``.
    """

    python_blocks: list[ManifestBlock] = field(default_factory=list)
    env: list[EnvEntry] = field(default_factory=list)
    compose_services: list[OwnedEntry] = field(default_factory=list)
    compose_volumes: list[OwnedEntry] = field(default_factory=list)
    dependencies: list[DependencyEntry] = field(default_factory=list)
    just_recipes: list[OwnedEntry] = field(default_factory=list)


# ── Contribution types (addon/template → pipeline) ────────────────────────────


@dataclass
class FileContribution:
    """A single file to be written into the project directory.

    ``dest`` may contain ``{{pkg_name}}`` which is resolved at apply time
    by plain string substitution (see :func:`resolve_dest_placeholder`).
    No other ``{{…}}`` placeholders are allowed in dest paths — use
    ``(( var_name ))`` (Jinja2 custom delimiters) in file content instead.
    """

    dest: str  # relative path; may contain ``{{pkg_name}}``
    source: str | None = None
    content: str | None = None
    template: bool = False


@dataclass
class ComposeService:
    """A Docker Compose service block contributed by a template or addon."""

    name: str
    image: str | None = None
    build: str | None = None
    ports: list[str] = field(default_factory=list)
    volumes: list[str] = field(default_factory=list)
    environment: dict[str, str] = field(default_factory=dict)
    env_file: list[str] = field(default_factory=list)
    command: str | None = None
    depends_on: list[str] | dict[str, dict[str, str]] = field(default_factory=list)
    develop_watch: list[dict[str, object]] = field(default_factory=list)
    healthcheck: dict[str, object] | None = None


@dataclass
class EnvVar:
    """A key/value pair to be appended to ``.env`` and ``.env.example``."""

    key: str
    default: str
    comment: str = ""


@dataclass
class Injection:
    """A snippet of code to be inserted at a named injection point."""

    point: str
    content: str
    addon_id: str = ""


@dataclass
class AddonHooks:
    """Typed container for optional addon module callbacks."""

    post_apply: Callable[[Context, FileSystem], None] | None = None
    health_check: Callable[[Path, ZenitLockfile], list[HealthIssue]] | None = None
    can_apply: Callable[[Path, ZenitLockfile], str | None] | None = None
    can_remove: Callable[[Path, ZenitLockfile], str | None] | None = None


@dataclass
class AddonConfig:
    """All contributions made by a single addon."""

    id: str
    description: str
    requires: list[str] = field(default_factory=list)
    conflicts_with: list[str] = field(default_factory=list)
    templates: list[str] = field(default_factory=list)  # empty = all templates allowed
    dirs: list[str] = field(default_factory=list)
    files: list[FileContribution] = field(default_factory=list)
    compose_services: list[ComposeService] = field(default_factory=list)
    compose_volumes: list[str] = field(default_factory=list)
    env_vars: list[EnvVar] = field(default_factory=list)
    deps: list[str] = field(default_factory=list)
    dev_deps: list[str] = field(default_factory=list)
    just_recipes: list[str] = field(default_factory=list)
    injections: list[Injection] = field(default_factory=list)
    _module: AddonHooks | None = field(default=None, repr=False, compare=False)


@dataclass
class TemplateConfig:
    """All contributions made by a template (blank, fastapi, …)."""

    id: str
    description: str
    requires_addons: list[str] = field(default_factory=list)
    injection_points: dict[str, InjectionPoint] = field(default_factory=dict)
    dirs: list[str] = field(default_factory=list)
    files: list[FileContribution] = field(default_factory=list)
    compose_services: list[ComposeService] = field(default_factory=list)
    compose_volumes: list[str] = field(default_factory=list)
    env_vars: list[EnvVar] = field(default_factory=list)
    deps: list[str] = field(default_factory=list)
    dev_deps: list[str] = field(default_factory=list)
    just_recipes: list[str] = field(default_factory=list)
    injections: list[Injection] = field(default_factory=list)


@dataclass
class Contributions:
    """Merged contributions from all selected addons (and the template)."""

    files: list[FileContribution] = field(default_factory=list)
    dirs: list[str] = field(default_factory=list)
    compose_services: list[ComposeService] = field(default_factory=list)
    compose_volumes: list[str] = field(default_factory=list)
    env_vars: list[EnvVar] = field(default_factory=list)
    deps: list[str] = field(default_factory=list)
    dev_deps: list[str] = field(default_factory=list)
    template_dev_deps: list[str] = field(default_factory=list)
    recipes: RecipeCollection = field(default_factory=RecipeCollection)
    injections: list[Injection] = field(default_factory=list)
    _addon_configs: list[AddonConfig] = field(default_factory=list)
