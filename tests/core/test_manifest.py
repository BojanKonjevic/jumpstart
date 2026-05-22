"""Unit tests for zenit.core.manifest.

Covers: TOML round-trip fidelity, all mutation helpers, idempotency contracts,
and I/O edge cases (missing file, corrupt TOML, project-section preservation).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import tomlkit

from zenit.core.manifest import (
    MANIFEST_SCHEMA_VERSION,
    add_compose_service,
    add_dependency,
    add_env_entry,
    add_just_recipe,
    add_python_block,
    read_manifest,
    remove_blocks_for_addon,
    write_manifest,
)
from zenit.schema.models import (
    DependencyEntry,
    EntrySource,
    EnvEntry,
    LocatorSpec,
    Manifest,
    ManifestBlock,
    OwnedEntry,
)

# ── fixtures ──────────────────────────────────────────────────────────────────


def _block(addon: str = "redis", point: str = "settings_fields") -> ManifestBlock:
    return ManifestBlock(
        addon=addon,
        point=point,
        file="src/myapp/settings.py",
        lines="15-16",
        fingerprint="sha256:aabbcc",
        fingerprint_normalised="sha256:ddeeff",
        locator=LocatorSpec(
            name="after_last_class_attribute",
            args={"class_name": "Settings"},
        ),
    )


def _full_manifest() -> Manifest:
    m = Manifest()
    m.python_blocks.append(_block("redis", "settings_fields"))
    m.python_blocks.append(_block("sentry", "lifespan_startup"))
    m.env.append(EnvEntry(key="DATABASE_URL", source=EntrySource.TEMPLATE, addon=""))
    m.env.append(EnvEntry(key="REDIS_URL", source=EntrySource.ADDON, addon="redis"))
    m.compose_services.append(
        OwnedEntry(name="db", source=EntrySource.TEMPLATE, addon="")
    )
    m.compose_services.append(
        OwnedEntry(name="redis", source=EntrySource.ADDON, addon="redis")
    )
    m.compose_volumes.append(
        OwnedEntry(name="redis-data", source=EntrySource.ADDON, addon="redis")
    )
    m.dependencies.append(
        DependencyEntry(
            package="redis",
            spec="redis>=5",
            source=EntrySource.ADDON,
            addon="redis",
            dev=False,
        )
    )
    m.dependencies.append(
        DependencyEntry(
            package="fakeredis",
            spec="fakeredis",
            source=EntrySource.ADDON,
            addon="redis",
            dev=True,
        )
    )
    m.just_recipes.append(
        OwnedEntry(name="redis-up", source=EntrySource.ADDON, addon="redis")
    )
    return m


# ── round-trip ────────────────────────────────────────────────────────────────


def test_roundtrip_empty_manifest(tmp_path: Path) -> None:
    write_manifest(tmp_path, Manifest())
    result = read_manifest(tmp_path)

    assert result.python_blocks == []
    assert result.env == []
    assert result.compose_services == []
    assert result.compose_volumes == []
    assert result.dependencies == []
    assert result.just_recipes == []


def test_roundtrip_full_manifest(tmp_path: Path) -> None:
    original = _full_manifest()
    write_manifest(tmp_path, original)
    result = read_manifest(tmp_path)

    assert len(result.python_blocks) == 2
    assert result.python_blocks[0].addon == "redis"
    assert result.python_blocks[0].point == "settings_fields"
    assert result.python_blocks[0].locator == LocatorSpec(
        name="after_last_class_attribute",
        args={"class_name": "Settings"},
    )
    assert result.python_blocks[1].addon == "sentry"

    assert len(result.env) == 2
    assert result.env[0] == EnvEntry(
        key="DATABASE_URL", source=EntrySource.TEMPLATE, addon=""
    )
    assert result.env[1] == EnvEntry(
        key="REDIS_URL", source=EntrySource.ADDON, addon="redis"
    )

    assert len(result.compose_services) == 2
    assert result.compose_services[1].name == "redis"

    assert len(result.compose_volumes) == 1
    assert result.compose_volumes[0].name == "redis-data"

    assert len(result.dependencies) == 2
    dep = result.dependencies[0]
    assert dep.package == "redis"
    assert dep.spec == "redis>=5"
    assert dep.dev is False
    assert result.dependencies[1].dev is True

    assert len(result.just_recipes) == 1
    assert result.just_recipes[0].name == "redis-up"


def test_read_preserves_project_section(tmp_path: Path) -> None:
    toml_path = tmp_path / ".zenit.toml"
    toml_path.write_text(
        '[project]\ntemplate = "fastapi"\naddons = ["redis"]\nzenit_version = "2.0.0"\n',
        encoding="utf-8",
    )

    write_manifest(tmp_path, _full_manifest())

    doc = tomlkit.parse(toml_path.read_text(encoding="utf-8"))
    assert doc["project"]["template"] == "fastapi"  # type: ignore[index]
    assert doc["project"]["addons"] == ["redis"]  # type: ignore[index]
    assert doc["project"]["zenit_version"] == "2.0.0"  # type: ignore[index]


# ── add_python_block ──────────────────────────────────────────────────────────


def test_add_python_block_appends(tmp_path: Path) -> None:
    m = Manifest()
    add_python_block(m, _block())
    assert len(m.python_blocks) == 1
    assert m.python_blocks[0].addon == "redis"


def test_add_python_block_appends_twice_for_same_block(tmp_path: Path) -> None:
    # Callers own deduplication; add_python_block is append-only.
    m = Manifest()
    b = _block()
    add_python_block(m, b)
    add_python_block(m, b)
    assert len(m.python_blocks) == 2


# ── remove_blocks_for_addon ───────────────────────────────────────────────────


def test_remove_addon_cleans_all_sections() -> None:
    m = _full_manifest()
    remove_blocks_for_addon(m, "redis")

    assert all(b.addon != "redis" for b in m.python_blocks)
    assert all(e.addon != "redis" for e in m.env)
    assert all(s.addon != "redis" for s in m.compose_services)
    assert all(v.addon != "redis" for v in m.compose_volumes)
    assert all(d.addon != "redis" for d in m.dependencies)
    assert all(r.addon != "redis" for r in m.just_recipes)


def test_remove_addon_preserves_others() -> None:
    m = _full_manifest()
    remove_blocks_for_addon(m, "redis")

    # Template-owned entries survive.
    assert any(e.source == "template" for e in m.env)
    assert any(s.source == "template" for s in m.compose_services)
    # Sentry block survives.
    assert any(b.addon == "sentry" for b in m.python_blocks)


# ── deduplication contracts ───────────────────────────────────────────────────


def test_add_env_entry_deduplicates_by_key() -> None:
    m = Manifest()
    add_env_entry(m, key="REDIS_URL", source=EntrySource.ADDON, addon="redis")
    add_env_entry(m, key="REDIS_URL", source=EntrySource.ADDON, addon="redis")
    assert len(m.env) == 1


def test_add_compose_service_deduplicates_by_name() -> None:
    m = Manifest()
    add_compose_service(m, name="redis", source=EntrySource.ADDON, addon="redis")
    add_compose_service(m, name="redis", source=EntrySource.ADDON, addon="redis")
    assert len(m.compose_services) == 1


def test_add_dependency_deduplicates_by_package() -> None:
    m = Manifest()
    add_dependency(
        m,
        package="redis",
        spec="redis>=5",
        source=EntrySource.ADDON,
        addon="redis",
        dev=False,
    )
    add_dependency(
        m,
        package="redis",
        spec="redis>=5",
        source=EntrySource.ADDON,
        addon="redis",
        dev=False,
    )
    assert len(m.dependencies) == 1


def test_add_just_recipe_deduplicates_by_name() -> None:
    m = Manifest()
    add_just_recipe(m, name="redis-up", source=EntrySource.ADDON, addon="redis")
    add_just_recipe(m, name="redis-up", source=EntrySource.ADDON, addon="redis")
    assert len(m.just_recipes) == 1


# ── file I/O edge cases ───────────────────────────────────────────────────────


def test_write_manifest_creates_file_if_absent(tmp_path: Path) -> None:
    assert not (tmp_path / ".zenit.toml").exists()
    write_manifest(tmp_path, Manifest())
    assert (tmp_path / ".zenit.toml").exists()


def test_read_manifest_returns_empty_when_file_absent(tmp_path: Path) -> None:
    result = read_manifest(tmp_path)
    assert result == Manifest()


def test_read_manifest_returns_empty_on_corrupt_toml(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / ".zenit.toml").write_text(
        "[[manifest.python_blocks\nbad toml ][[\n", encoding="utf-8"
    )

    result = read_manifest(tmp_path)

    assert result == Manifest()
    err = capsys.readouterr().err
    assert "Warning" in err
    assert ".zenit.toml" in err


# ── atomic write ──────────────────────────────────────────────────────────────


def test_write_manifest_leaves_no_temp_files(tmp_path: Path) -> None:
    write_manifest(tmp_path, _full_manifest())
    leftovers = [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    assert not leftovers


# ── schema version ────────────────────────────────────────────────────────────


def test_schema_version_constant_is_2() -> None:
    assert MANIFEST_SCHEMA_VERSION == 2
