"""Unit tests for zenit.core.handlers.justfile_handler.JustfileHandler.

Covers: can_handle() dispatches by filename not suffix, apply() appends
recipes and skips duplicates, remove() deletes by line range, and
missing-file no-op on remove.
"""

from __future__ import annotations

from pathlib import Path

from zenit.core.handlers.justfile_handler import JustfileHandler
from zenit.schema.models import ManifestBlock

# ── helpers ───────────────────────────────────────────────────────────────────


def _handler() -> JustfileHandler:
    return JustfileHandler()


def _block(lines: str, file: Path) -> ManifestBlock:
    return ManifestBlock(
        addon="docker",
        point="just_recipe",
        file=str(file),
        lines=lines,
        fingerprint="sha256:abc",
        fingerprint_normalised="sha256:def",
        locator={"name": "at_file_end", "args": {}},
    )


# ── can_handle() ──────────────────────────────────────────────────────────────


def test_can_handle_matches_justfile_by_name() -> None:
    h = _handler()
    assert h.can_handle(Path("justfile")) is True
    assert h.can_handle(Path("project/justfile")) is True


def test_can_handle_rejects_by_suffix() -> None:
    h = _handler()
    assert h.can_handle(Path("justfile.bak")) is False
    assert h.can_handle(Path("Makefile")) is False
    assert h.can_handle(Path("mod.py")) is False


# ── apply() ───────────────────────────────────────────────────────────────────


def test_apply_appends_recipe(tmp_path: Path) -> None:
    f = tmp_path / "justfile"
    f.write_text("run:\n    uvicorn src.myapp.main:app\n", encoding="utf-8")
    recipe = "\ndocker-up:\n    docker compose up -d\n"

    _handler().apply(f, recipe, "", {})

    text = f.read_text()
    assert "docker-up" in text
    # Existing recipe preserved
    assert "run:" in text


def test_apply_skips_duplicate_recipe_name(tmp_path: Path) -> None:
    f = tmp_path / "justfile"
    original = "docker-up:\n    docker compose up -d\n"
    f.write_text(original, encoding="utf-8")

    _handler().apply(f, "docker-up:\n    docker compose up --build\n", "", {})

    # File must be byte-for-byte identical — no write occurred
    assert f.read_text() == original


# ── remove() ──────────────────────────────────────────────────────────────────


def test_remove_deletes_recipe_by_lines(tmp_path: Path) -> None:
    f = tmp_path / "justfile"
    f.write_text(
        "run:\n"
        "    uvicorn src.myapp.main:app\n"
        "\n"
        "docker-up:\n"
        "    docker compose up -d\n",
        encoding="utf-8",
    )
    block = _block("4-5", f)

    _handler().remove(f, block)

    text = f.read_text()
    assert "docker-up" not in text
    assert "run:" in text


def test_remove_missing_file_is_noop(tmp_path: Path) -> None:
    f = tmp_path / "justfile"
    block = _block("1-2", f)
    _handler().remove(f, block)  # must not raise
    assert not f.exists()
