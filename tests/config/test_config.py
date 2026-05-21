"""Tests for zenit.config — user config loading."""

import sys
from pathlib import Path

import pytest

from zenit.config.config import ZenitConfig, config_path, load_config


def test_load_config_returns_empty_when_file_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "nonexistent"))
    cfg = load_config()
    assert cfg.default_template is None
    assert cfg.default_addons == []


def test_load_config_returns_empty_on_corrupt_toml(tmp_path, monkeypatch):
    config_dir = tmp_path / "zenit"
    config_dir.mkdir(parents=True)
    (config_dir / "zenit.toml").write_text("NOT VALID [[[")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    cfg = load_config()
    assert cfg.default_template is None
    assert cfg.default_addons == []


def test_load_config_reads_default_template(tmp_path, monkeypatch):
    config_dir = tmp_path / "zenit"
    config_dir.mkdir(parents=True)
    (config_dir / "zenit.toml").write_text('default_template = "fastapi"\n')
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    cfg = load_config()
    assert cfg.default_template == "fastapi"


def test_load_config_reads_default_addons(tmp_path, monkeypatch):
    config_dir = tmp_path / "zenit"
    config_dir.mkdir(parents=True)
    (config_dir / "zenit.toml").write_text(
        'default_addons = ["docker", "github-actions"]\n'
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    cfg = load_config()
    assert cfg.default_addons == ["docker", "github-actions"]


def test_load_config_ignores_non_string_template(tmp_path, monkeypatch):
    config_dir = tmp_path / "zenit"
    config_dir.mkdir(parents=True)
    (config_dir / "zenit.toml").write_text("default_template = 42\n")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    cfg = load_config()
    assert cfg.default_template is None


def test_load_config_ignores_non_list_addons(tmp_path, monkeypatch):
    config_dir = tmp_path / "zenit"
    config_dir.mkdir(parents=True)
    (config_dir / "zenit.toml").write_text('default_addons = "docker"\n')
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    cfg = load_config()
    assert cfg.default_addons == []


def test_load_config_filters_non_string_addon_entries(tmp_path, monkeypatch):
    config_dir = tmp_path / "zenit"
    config_dir.mkdir(parents=True)
    (config_dir / "zenit.toml").write_text('default_addons = ["docker", 99, "redis"]\n')
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    cfg = load_config()
    assert cfg.default_addons == ["docker", "redis"]


def test_load_config_reads_both_fields(tmp_path, monkeypatch):
    config_dir = tmp_path / "zenit"
    config_dir.mkdir(parents=True)
    (config_dir / "zenit.toml").write_text(
        'default_template = "blank"\ndefault_addons = ["docker"]\n'
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    cfg = load_config()
    assert cfg.default_template == "blank"
    assert cfg.default_addons == ["docker"]


def test_zenitconfig_defaults():
    cfg = ZenitConfig()
    assert cfg.default_template is None
    assert cfg.default_addons == []


@pytest.mark.skipif(sys.platform == "win32", reason="XDG only on non-Windows")
def test_config_path_respects_xdg(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    path = config_path()
    assert path == tmp_path / "zenit" / "zenit.toml"


@pytest.mark.skipif(sys.platform == "win32", reason="XDG only on non-Windows")
def test_config_path_defaults_to_dot_config(monkeypatch):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    path = config_path()
    assert path == Path.home() / ".config" / "zenit" / "zenit.toml"
