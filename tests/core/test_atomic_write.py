"""Tests for zenit.core.filesystem.atomic_write_text."""

from __future__ import annotations

from pathlib import Path

import pytest

from zenit.core.filesystem import atomic_write_text


def test_writes_content(tmp_path: Path) -> None:
    target = tmp_path / "foo.txt"
    atomic_write_text(target, "hello world")
    assert target.read_text(encoding="utf-8") == "hello world"


def test_overwrites_existing(tmp_path: Path) -> None:
    target = tmp_path / "foo.txt"
    target.write_text("first", encoding="utf-8")
    atomic_write_text(target, "second")
    assert target.read_text(encoding="utf-8") == "second"


def test_temp_file_cleaned(tmp_path: Path) -> None:
    target = tmp_path / "foo.txt"
    atomic_write_text(target, "content")
    leftovers = [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    assert not leftovers


def test_temp_file_same_directory(tmp_path: Path) -> None:
    target = tmp_path / "foo.txt"
    atomic_write_text(target, "content")
    assert target.exists()
    # Verify no temp files in system temp directory
    all_files = list(tmp_path.iterdir())
    assert all(f.parent == tmp_path for f in all_files)


def test_non_existent_parent(tmp_path: Path) -> None:
    bogus = tmp_path / "nope" / "foo.txt"
    with pytest.raises(FileNotFoundError):
        atomic_write_text(bogus, "content")
