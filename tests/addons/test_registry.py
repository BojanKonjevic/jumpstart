"""Tests for addon registry — metadata (TOML) and lazy exec."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from zenit.addons._registry import get_addon, list_addons
from zenit.schema.exceptions import ZenitError

# ── list_addons() — metadata only, no exec ────────────────────────────────


def test_list_addons_returns_meta(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """list_addons() reads addon.toml and returns AddonMeta with no exec."""
    list_addons.cache_clear()
    addon_dir = tmp_path / "myaddon"
    addon_dir.mkdir()
    (addon_dir / "addon.toml").write_text(
        dedent("""\
            [addon]
            id = "myaddon"
            description = "My test addon"
            requires = ["something"]
            templates = ["fastapi"]
        """)
    )
    monkeypatch.setattr("zenit.addons._registry._HERE", tmp_path)
    metas = list_addons()
    assert len(metas) == 1
    assert metas[0].id == "myaddon"
    assert metas[0].description == "My test addon"
    assert metas[0].requires == ["something"]
    assert metas[0].templates == ["fastapi"]


def test_list_addons_skips_dir_without_toml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """An addon directory without addon.toml is silently skipped."""
    list_addons.cache_clear()
    empty = tmp_path / "empty_addon"
    empty.mkdir()
    monkeypatch.setattr("zenit.addons._registry._HERE", tmp_path)
    assert list_addons() == []


def test_list_addons_all_real_addons_have_toml():
    """Every real addon directory has a valid addon.toml with the right id."""
    list_addons.cache_clear()
    metas = list_addons()
    assert len(metas) > 0
    for m in metas:
        assert m.id
        assert m.description


# ── get_addon() — lazy exec ────────────────────────────────────────────────


def test_get_addon_execs_addon_py(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """get_addon() execs the specific addon.py and returns AddonConfig."""
    get_addon.cache_clear()
    addon_dir = tmp_path / "myaddon"
    addon_dir.mkdir()
    (addon_dir / "addon.toml").write_text(
        dedent("""\
            [addon]
            id = "myaddon"
            description = "My test addon"
        """)
    )
    (addon_dir / "addon.py").write_text(
        dedent("""\
            from zenit.schema.models import AddonConfig
            config = AddonConfig(id="myaddon", description="My test addon")
        """)
    )
    monkeypatch.setattr("zenit.addons._registry._HERE", tmp_path)
    cfg = get_addon("myaddon")
    assert cfg.id == "myaddon"
    assert cfg.description == "My test addon"


def test_get_addon_propagates_import_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A syntax/import error in addon.py must propagate from get_addon()."""
    get_addon.cache_clear()
    broken = tmp_path / "broken_addon"
    broken.mkdir()
    (broken / "addon.toml").write_text(
        dedent("""\
            [addon]
            id = "broken_addon"
            description = "Broken"
        """)
    )
    (broken / "addon.py").write_text(
        dedent("""\
            from does_not_exist import foo
            config = "typo"
        """)
    )
    monkeypatch.setattr("zenit.addons._registry._HERE", tmp_path)
    with pytest.raises(ZenitError, match="Failed to load addon 'broken_addon'"):
        get_addon("broken_addon")


def test_get_addon_filenotfound_for_missing_addon():
    """get_addon() raises FileNotFoundError for a non-existent addon id."""
    get_addon.cache_clear()
    with pytest.raises(FileNotFoundError):
        get_addon("nonexistent_addon_id_xyz")


# ── get_available_addons — backward compatible ─────────────────────────────


def test_available_addons_still_load():
    """All real addons in the repo load without error (backward compat)."""
    addon_ids = [m.id for m in list_addons()]
    for aid in addon_ids:
        get_addon(aid)  # smoke test: each loads without error
