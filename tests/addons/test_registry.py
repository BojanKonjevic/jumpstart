"""Tests for addon discovery error handling."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from zenit.addons._registry import get_available_addons


def test_broken_addon_propagates_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A syntax/import error in an addon.py must propagate, not skip."""
    get_available_addons.cache_clear()
    broken = tmp_path / "broken_addon"
    broken.mkdir()
    (broken / "addon.py").write_text(
        dedent("""\
            from does_not_exist import foo
            config = "typo"
        """)
    )
    monkeypatch.setattr("zenit.addons._registry._HERE", tmp_path)
    with pytest.raises(ImportError):
        get_available_addons()


def test_empty_addon_dir_skipped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """An addon directory without addon.py is silently skipped (not an error)."""
    get_available_addons.cache_clear()
    empty = tmp_path / "empty_addon"
    empty.mkdir()
    monkeypatch.setattr("zenit.addons._registry._HERE", tmp_path)
    assert get_available_addons() == []


def test_valid_addons_still_load():
    """All real addons in the repo load without error."""
    get_available_addons.cache_clear()
    addons = get_available_addons()
    assert len(addons) > 0
