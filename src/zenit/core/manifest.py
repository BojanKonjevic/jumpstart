"""Zenit manifest — .zenit.toml [manifest] section.

The manifest is the single source of truth for everything zenit has injected
into a project.  It is written at scaffold time and updated by every
``zenit add`` / ``zenit remove``.  ``zenit doctor`` reads it to verify
integrity.

Schema version
--------------
``MANIFEST_SCHEMA_VERSION = 2`` — bump this constant if the normalisation
algorithm or the manifest structure changes in a breaking way.  ``read()``
will warn (not error) when the stored version differs from the current one.

Normalisation contract
----------------------
``fingerprint_normalised`` is defined as SHA-256 of the string produced by:

    1. Parse the code with ``libcst.parse_module(code)``.
    2. Serialise back via ``.code`` (canonical libcst output).
    3. Strip trailing whitespace from every line.
    4. Collapse runs of 3+ consecutive newlines to exactly two newlines.

**Do not change this definition without bumping MANIFEST_SCHEMA_VERSION.**
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path
from typing import Any

import libcst
import tomlkit
import tomlkit.items
from jinja2 import Environment

from zenit.core.constants import _RECIPE_NAME_RE
from zenit.core.filesystem import atomic_write_text
from zenit.schema.models import (
    AddonConfig,
    DependencyEntry,
    EntrySource,
    EnvEntry,
    LocatorSpec,
    Manifest,
    ManifestBlock,
    OwnedEntry,
)

LOCKFILE_NAME = ".zenit.toml"
MANIFEST_SCHEMA_VERSION = 2


# ── Public API ────────────────────────────────────────────────────────────────


def read_manifest(project_dir: Path) -> Manifest:
    """Read the ``[manifest]`` section from *project_dir*/.zenit.toml.

    Returns an empty ``Manifest`` if the file is absent, cannot be parsed,
    or has no ``[manifest]`` section (e.g. a v1 project).
    """
    path = project_dir / LOCKFILE_NAME
    if not path.exists():
        return Manifest()

    try:
        doc = tomlkit.parse(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(
            f"Warning: could not parse '{path}': {exc}. "
            f"Manifest will be treated as empty. Run 'zenit doctor' to verify.",
            file=sys.stderr,
        )
        return Manifest()

    raw: Any = doc.get("manifest", {})
    if not isinstance(raw, dict):
        return Manifest()

    return _decode_manifest(raw)


def write_manifest(project_dir: Path, manifest: Manifest) -> None:
    """Write *manifest* into the ``[manifest]`` section of *project_dir*/.zenit.toml.

    Preserves the existing ``[project]`` section and all comments.
    Creates the file if it does not exist (though normally ``write_lockfile``
    creates it first at scaffold time).
    """
    path = project_dir / LOCKFILE_NAME
    if path.exists():
        doc = tomlkit.parse(path.read_text(encoding="utf-8"))
    else:
        doc = tomlkit.document()

    doc["manifest"] = _encode_manifest(manifest)
    atomic_write_text(path, tomlkit.dumps(doc))


# ── Manifest mutation helpers ─────────────────────────────────────────────────


def add_python_block(manifest: Manifest, block: ManifestBlock) -> None:
    manifest.python_blocks.append(block)


def remove_blocks_for_addon(manifest: Manifest, addon_id: str) -> None:
    """Remove all manifest entries that belong to *addon_id*."""
    manifest.python_blocks = [b for b in manifest.python_blocks if b.addon != addon_id]
    manifest.env = [e for e in manifest.env if e.addon != addon_id]
    manifest.compose_services = [
        s for s in manifest.compose_services if s.addon != addon_id
    ]
    manifest.compose_volumes = [
        v for v in manifest.compose_volumes if v.addon != addon_id
    ]
    manifest.dependencies = [d for d in manifest.dependencies if d.addon != addon_id]
    manifest.just_recipes = [r for r in manifest.just_recipes if r.addon != addon_id]


def add_env_entry(
    manifest: Manifest, key: str, source: EntrySource, addon: str
) -> None:
    if not any(e.key == key for e in manifest.env):
        manifest.env.append(EnvEntry(key=key, source=source, addon=addon))


def add_compose_service(
    manifest: Manifest, name: str, source: EntrySource, addon: str
) -> None:
    if not any(s.name == name for s in manifest.compose_services):
        manifest.compose_services.append(
            OwnedEntry(name=name, source=source, addon=addon)
        )


def add_compose_volume(
    manifest: Manifest, name: str, source: EntrySource, addon: str
) -> None:
    if not any(v.name == name for v in manifest.compose_volumes):
        manifest.compose_volumes.append(
            OwnedEntry(name=name, source=source, addon=addon)
        )


def add_dependency(
    manifest: Manifest,
    package: str,
    spec: str,
    source: EntrySource,
    addon: str,
    dev: bool,
) -> None:
    if not any(d.package == package for d in manifest.dependencies):
        manifest.dependencies.append(
            DependencyEntry(
                package=package, spec=spec, source=source, addon=addon, dev=dev
            )
        )


def add_just_recipe(
    manifest: Manifest, name: str, source: EntrySource, addon: str
) -> None:
    if not any(r.name == name for r in manifest.just_recipes):
        manifest.just_recipes.append(OwnedEntry(name=name, source=source, addon=addon))


def _pkg_name(dep: str) -> str:
    match = re.match(r"^([a-zA-Z0-9_.-]+)", dep)
    return match.group(1).lower().replace("-", "_") if match else dep.lower()


def record_addon_manifest_entries(
    manifest: Manifest,
    addon_cfg: AddonConfig,
    string_env: Environment,
    render_vars: dict[str, object],
) -> None:
    addon_id = addon_cfg.id
    for ev in addon_cfg.env_vars:
        add_env_entry(manifest, ev.key, source=EntrySource.ADDON, addon=addon_id)
    for svc in addon_cfg.compose_services:
        add_compose_service(
            manifest, svc.name, source=EntrySource.ADDON, addon=addon_id
        )
    for vol in addon_cfg.compose_volumes:
        add_compose_volume(manifest, vol, source=EntrySource.ADDON, addon=addon_id)
    for dep in addon_cfg.deps:
        add_dependency(
            manifest,
            _pkg_name(dep),
            dep,
            source=EntrySource.ADDON,
            addon=addon_id,
            dev=False,
        )
    for dep in addon_cfg.dev_deps:
        add_dependency(
            manifest,
            _pkg_name(dep),
            dep,
            source=EntrySource.ADDON,
            addon=addon_id,
            dev=True,
        )
    for recipe_raw in addon_cfg.just_recipes:
        rendered = string_env.from_string(recipe_raw).render(**render_vars)
        m = _RECIPE_NAME_RE.search(rendered)
        if m:
            add_just_recipe(
                manifest, m.group(1), source=EntrySource.ADDON, addon=addon_id
            )


# ── Fingerprinting ────────────────────────────────────────────────────────────


def fingerprint(code: str) -> tuple[str, str]:
    """Return ``(fingerprint, fingerprint_normalised)`` for *code*.

    Both values are ``"sha256:<hex>"``.

    See module docstring for the exact normalisation contract.
    Do NOT change ``_normalise`` without bumping ``MANIFEST_SCHEMA_VERSION``.

    If *code* is not a valid Python module (e.g. a class-body fragment such as
    a single annotated attribute), libcst round-tripping is skipped and the
    raw text is hashed directly.  This means the hash is computed without a
    canonical libcst round-trip: Stage A and B removal will not match, and
    removal will fall through to Stage C (fuzzy match).

    This is an explicit trade-off: fingerprinting must not crash on fragments,
    but removal precision degrades for syntactically invalid blocks.
    """
    try:
        module = libcst.parse_module(code)
        canonical = module.code
    except Exception:
        # Class-body fragments (e.g. single annotated attributes) are not
        # valid modules. Fall back to raw text so fingerprinting doesn't
        # crash, but note that Stage A/B removal may fall through to fuzzy.
        canonical = code
    raw_hash = hashlib.sha256(canonical.encode()).hexdigest()
    norm_hash = hashlib.sha256(_normalise(canonical).encode()).hexdigest()
    return f"sha256:{raw_hash}", f"sha256:{norm_hash}"


def normalised_fingerprint_of(code: str) -> str:
    """Return only the normalised fingerprint for *code*."""
    return fingerprint(code)[1]


def _normalise(code: str) -> str:
    """Canonical normalisation for formatter-resilient fingerprinting.

    Definition (frozen — do not change without bumping MANIFEST_SCHEMA_VERSION):
      1. libcst round-trip  →  canonical serialisation.
      2. Strip trailing whitespace from every line.
      3. Collapse runs of 3+ consecutive newlines to exactly two.
    """
    lines = [line.rstrip() for line in code.splitlines()]
    joined = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", joined)


# ── TOML encode / decode ──────────────────────────────────────────────────────


def _encode_section(
    tbl: tomlkit.items.Table,
    items: list[Any],
    section_name: str,
    field_map: list[tuple[str, str]],
) -> None:
    if not items:
        return
    arr = tomlkit.aot()
    for item in items:
        entry = tomlkit.table()
        for toml_key, attr_name in field_map:
            entry.add(toml_key, getattr(item, attr_name))
        arr.append(entry)
    tbl.add(section_name, arr)


def _encode_manifest(m: Manifest) -> tomlkit.items.Table:
    tbl = tomlkit.table()

    if m.python_blocks:
        arr = tomlkit.aot()
        for b in m.python_blocks:
            item = tomlkit.table()
            item.add("addon", b.addon)
            item.add("point", b.point)
            item.add("file", b.file)
            item.add("lines", b.lines)
            item.add("fingerprint", b.fingerprint)
            item.add("fingerprint_normalised", b.fingerprint_normalised)
            loc = tomlkit.table()
            loc.add("name", b.locator.name)
            loc.add("args", b.locator.args)
            item.add("locator", loc)
            arr.append(item)
        tbl.add("python_blocks", arr)

    _encode_section(
        tbl, m.env, "env", [("key", "key"), ("source", "source"), ("addon", "addon")]
    )
    _encode_section(
        tbl,
        m.compose_services,
        "compose_services",
        [("name", "name"), ("source", "source"), ("addon", "addon")],
    )
    _encode_section(
        tbl,
        m.compose_volumes,
        "compose_volumes",
        [("name", "name"), ("source", "source"), ("addon", "addon")],
    )
    _encode_section(
        tbl,
        m.dependencies,
        "dependencies",
        [
            ("package", "package"),
            ("spec", "spec"),
            ("source", "source"),
            ("addon", "addon"),
            ("dev", "dev"),
        ],
    )
    _encode_section(
        tbl,
        m.just_recipes,
        "just_recipes",
        [("name", "name"), ("source", "source"), ("addon", "addon")],
    )

    return tbl


def _parse_source(raw: str) -> EntrySource:
    """Parse a TOML source field into an EntrySource, defaulting to TEMPLATE."""
    try:
        return EntrySource(raw)
    except ValueError:
        return EntrySource.TEMPLATE


type _FieldMapEntry = tuple[
    str, str, Any, Any
]  # toml_key, attr_name, default, transform


def _decode_section(
    raw: dict[str, Any],
    section_name: str,
    model_cls: type[Any],
    field_map: list[_FieldMapEntry],
) -> list[Any]:
    result: list[Any] = []
    for item in raw.get(section_name, []):
        kwargs: dict[str, Any] = {}
        for toml_key, attr_name, default, transform in field_map:
            val = item.get(toml_key, default)
            if transform is not None:
                val = transform(val)
            kwargs[attr_name] = val
        result.append(model_cls(**kwargs))
    return result


def _decode_manifest(raw: dict[str, Any]) -> Manifest:
    m = Manifest()

    for b in raw.get("python_blocks", []):
        loc = b.get("locator", {})
        m.python_blocks.append(
            ManifestBlock(
                addon=b.get("addon", ""),
                point=b.get("point", ""),
                file=b.get("file", ""),
                lines=b.get("lines", ""),
                fingerprint=b.get("fingerprint", ""),
                fingerprint_normalised=b.get("fingerprint_normalised", ""),
                locator=LocatorSpec(
                    name=loc.get("name", ""),
                    args=dict(loc.get("args", {})),
                ),
            )
        )

    m.env = _decode_section(
        raw,
        "env",
        EnvEntry,
        [
            ("key", "key", "", None),
            ("source", "source", "", _parse_source),
            ("addon", "addon", "", None),
        ],
    )
    m.compose_services = _decode_section(
        raw,
        "compose_services",
        OwnedEntry,
        [
            ("name", "name", "", None),
            ("source", "source", "", _parse_source),
            ("addon", "addon", "", None),
        ],
    )
    m.compose_volumes = _decode_section(
        raw,
        "compose_volumes",
        OwnedEntry,
        [
            ("name", "name", "", None),
            ("source", "source", "", _parse_source),
            ("addon", "addon", "", None),
        ],
    )
    m.dependencies = _decode_section(
        raw,
        "dependencies",
        DependencyEntry,
        [
            ("package", "package", "", None),
            ("spec", "spec", "", None),
            ("source", "source", "", _parse_source),
            ("addon", "addon", "", None),
            ("dev", "dev", False, bool),
        ],
    )
    m.just_recipes = _decode_section(
        raw,
        "just_recipes",
        OwnedEntry,
        [
            ("name", "name", "", None),
            ("source", "source", "", _parse_source),
            ("addon", "addon", "", None),
        ],
    )

    return m
