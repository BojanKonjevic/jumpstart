"""Unit tests for zenit.core.handlers.env_handler.EnvHandler.

Covers: apply() append semantics, duplicate-key skip, comment/blank
preservation, trailing-newline insertion, remove() by line range, and
missing-file no-op on remove.
"""

from __future__ import annotations

from pathlib import Path

from zenit.core.handlers.env_handler import EnvHandler
from zenit.core.handlers.locators import LOCATOR_AT_FILE_END
from zenit.schema.models import LocatorSpec, ManifestBlock

# ── helpers ───────────────────────────────────────────────────────────────────


def _handler() -> EnvHandler:
    return EnvHandler()


def _block(lines: str, file: Path) -> ManifestBlock:
    return ManifestBlock(
        addon="redis",
        point="env_vars",
        file=str(file),
        lines=lines,
        fingerprint="sha256:abc",
        fingerprint_normalised="sha256:def",
        locator=LocatorSpec(name=LOCATOR_AT_FILE_END, args={}),
    )


# ── apply() ───────────────────────────────────────────────────────────────────


def test_apply_appends_new_vars(tmp_path: Path) -> None:
    f = tmp_path / ".env"
    f.write_text("DATABASE_URL=postgresql://localhost\n", encoding="utf-8")

    _handler().apply(f, "REDIS_URL=redis://localhost\nREDIS_POOL=10\n", "", {})

    text = f.read_text()
    assert "REDIS_URL=redis://localhost" in text
    assert "REDIS_POOL=10" in text
    # Original line is preserved
    assert "DATABASE_URL=postgresql://localhost" in text


def test_apply_skips_existing_keys(tmp_path: Path) -> None:
    f = tmp_path / ".env"
    original = "REDIS_URL=redis://localhost\n"
    f.write_text(original, encoding="utf-8")

    _handler().apply(f, "REDIS_URL=redis://other\n", "", {})

    # File must be byte-for-byte identical — no write occurred
    assert f.read_text() == original


def test_apply_preserves_comments_and_blanks(tmp_path: Path) -> None:
    f = tmp_path / ".env"
    f.write_text(
        "# database\nDATABASE_URL=postgresql://localhost\n\n", encoding="utf-8"
    )

    _handler().apply(f, "REDIS_URL=redis://localhost\n", "", {})

    text = f.read_text()
    assert "# database" in text
    assert text.count("\n\n") >= 1  # blank line preserved


def test_apply_adds_trailing_newline_before_new_content(tmp_path: Path) -> None:
    f = tmp_path / ".env"
    # File does NOT end with \n
    f.write_text("DATABASE_URL=postgresql://localhost", encoding="utf-8")

    _handler().apply(f, "REDIS_URL=redis://localhost\n", "", {})

    text = f.read_text()
    # The two vars must be on separate lines — no concatenation
    assert "localhost\nREDIS_URL" in text or "localhost\nREDIS_URL" in text.replace(
        "\r\n", "\n"
    )


# ── remove() ──────────────────────────────────────────────────────────────────


def test_remove_deletes_lines_by_range(tmp_path: Path) -> None:
    f = tmp_path / ".env"
    f.write_text(
        "DATABASE_URL=postgresql://localhost\n"
        "REDIS_URL=redis://localhost\n"
        "DEBUG=true\n",
        encoding="utf-8",
    )
    block = _block("2-2", f)

    _handler().remove(f, block)

    text = f.read_text()
    assert "REDIS_URL" not in text
    assert "DATABASE_URL" in text
    assert "DEBUG" in text


def test_remove_missing_file_is_noop(tmp_path: Path) -> None:
    f = tmp_path / ".env"
    # File does not exist — remove must return without raising
    block = _block("1-1", f)
    _handler().remove(f, block)  # must not raise
    assert not f.exists()
