"""Unit tests for zenit.core.handlers.toml_handler.TomlHandler.

Covers: apply() append semantics and duplicate top-level key skip,
remove() produces valid TOML, and missing-file no-op on remove.
"""

from __future__ import annotations

from pathlib import Path

import tomlkit

from zenit.core.handlers.locators import LOCATOR_AT_FILE_END
from zenit.core.handlers.toml_handler import TomlHandler
from zenit.schema.models import LocatorSpec, ManifestBlock

# ── helpers ───────────────────────────────────────────────────────────────────


def _handler() -> TomlHandler:
    return TomlHandler()


def _block(lines: str, file: Path) -> ManifestBlock:
    return ManifestBlock(
        addon="redis",
        point="toml_section",
        file=str(file),
        lines=lines,
        fingerprint="",
        fingerprint_normalised="",
        locator=LocatorSpec(name=LOCATOR_AT_FILE_END, args={}),
    )


# ── apply() ───────────────────────────────────────────────────────────────────


def test_apply_appends_new_section(tmp_path: Path) -> None:
    f = tmp_path / "pyproject.toml"
    f.write_text(
        '[project]\nname = "myapp"\n',
        encoding="utf-8",
    )
    addition = "[tool.redis]\npool_size = 10\n"

    _handler().apply(f, addition, "", {})

    text = f.read_text()
    assert "[tool.redis]" in text
    assert "pool_size = 10" in text
    # Original section preserved
    assert "[project]" in text
    assert 'name = "myapp"' in text


def test_apply_skips_existing_top_level_key(tmp_path: Path) -> None:
    f = tmp_path / "pyproject.toml"
    original = '[project]\nname = "myapp"\n'
    f.write_text(original, encoding="utf-8")

    # "project" key already exists - no write must occur
    _handler().apply(f, '[project]\nname = "other"\n', "", {})

    assert f.read_text() == original


def test_remove_deletes_by_lines(tmp_path: Path) -> None:
    f = tmp_path / "pyproject.toml"
    f.write_text(
        '[project]\nname = "myapp"\n[tool.redis]\npool_size = 10\n',
        encoding="utf-8",
    )
    block = _block("3-4", f)

    _handler().remove(f, block)

    text = f.read_text()
    assert "[tool.redis]" not in text
    # Remaining TOML is valid
    parsed = tomlkit.parse(text)
    assert "project" in parsed


def test_remove_missing_file_is_noop(tmp_path: Path) -> None:
    f = tmp_path / "pyproject.toml"
    block = _block("1-2", f)
    _handler().remove(f, block)  # must not raise
    assert not f.exists()
