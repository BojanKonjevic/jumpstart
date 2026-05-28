"""Unit tests for zenit.core.handlers.yaml_handler.YamlHandler.

Covers: apply() merge semantics and duplicate-skip by first key,
remove() by line range, and missing-file no-op on remove.
"""

from __future__ import annotations

from pathlib import Path

from zenit.core.handlers.locators import LOCATOR_AT_FILE_END
from zenit.core.handlers.yaml_handler import YamlHandler
from zenit.schema.models import LocatorSpec, ManifestBlock

# ── helpers ───────────────────────────────────────────────────────────────────


def _handler() -> YamlHandler:
    return YamlHandler()


def _block(lines: str, file: Path) -> ManifestBlock:
    return ManifestBlock(
        addon="redis",
        point="compose_service",
        file=str(file),
        lines=lines,
        fingerprint="",
        fingerprint_normalised="",
        locator=LocatorSpec(name=LOCATOR_AT_FILE_END, args={}),
    )


# ── apply() ───────────────────────────────────────────────────────────────────


def test_apply_merges_service_and_volume(tmp_path: Path) -> None:
    f = tmp_path / "compose.yml"
    f.write_text(
        "services:\n  app:\n    image: myapp:latest\n",
        encoding="utf-8",
    )
    addition = "  redis:\n    image: redis:7-alpine\n    ports:\n      - '6379:6379'\n"

    _handler().apply(f, addition, "", {})

    text = f.read_text()
    assert "redis" in text
    # Existing content preserved
    assert "app" in text
    assert "myapp:latest" in text


def test_apply_skips_existing_service_by_first_key(tmp_path: Path) -> None:
    f = tmp_path / "compose.yml"
    original = "services:\n  redis:\n    image: redis:6\n"
    f.write_text(original, encoding="utf-8")

    _handler().apply(f, "  redis:\n    image: redis:7-alpine\n", "", {})

    # File must be byte-for-byte identical — no write occurred
    assert f.read_text() == original


def test_remove_deletes_block_by_lines(tmp_path: Path) -> None:
    f = tmp_path / "compose.yml"
    f.write_text(
        "services:\n  app:\n    image: myapp\n  redis:\n    image: redis:7-alpine\n",
        encoding="utf-8",
    )
    block = _block("4-5", f)

    _handler().remove(f, block)

    text = f.read_text()
    assert "redis" not in text
    assert "app" in text
    assert "myapp" in text


def test_remove_missing_file_is_noop(tmp_path: Path) -> None:
    f = tmp_path / "compose.yml"
    block = _block("1-2", f)
    _handler().remove(f, block)  # must not raise
    assert not f.exists()
