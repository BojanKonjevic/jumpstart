"""Tests for zenit.core._apply_loader - loading apply() from a Python file."""

from __future__ import annotations

from pathlib import Path

import pytest

from zenit.core._apply_loader import load_apply
from zenit.schema.exceptions import ZenitError


def test_load_apply_syntax_error_in_module(tmp_path: Path) -> None:
    apply_file = tmp_path / "apply.py"
    apply_file.write_text("if True\n    pass", encoding="utf-8")
    with pytest.raises(SyntaxError):
        load_apply(apply_file)


def test_load_apply_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "nonexistent" / "apply.py"
    with pytest.raises(ZenitError, match="file not found"):
        load_apply(missing)


def test_load_apply_missing_apply_function(tmp_path: Path) -> None:
    apply_file = tmp_path / "apply.py"
    apply_file.write_text("x = 1", encoding="utf-8")
    with pytest.raises(AttributeError, match="no attribute"):
        load_apply(apply_file)
