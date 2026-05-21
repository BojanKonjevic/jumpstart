"""Tests for zenit.checks — precondition checking for zenit add."""

from pathlib import Path

import pytest

from zenit.addons.checks import check_can_add
from zenit.core.lockfile import write_lockfile
from zenit.schema.exceptions import ZenitError
from zenit.schema.models import AddonConfig


def _make_addon(id: str, requires: list[str] | None = None) -> AddonConfig:
    return AddonConfig(id=id, description=f"{id} addon", requires=requires or [])


def _write_lock(project_dir: Path, template: str, addons: list[str]) -> None:
    write_lockfile(project_dir, template, addons)


def test_raises_when_no_lockfile(tmp_path):
    available = [_make_addon("docker")]
    with pytest.raises(ZenitError, match=".zenit.toml"):
        check_can_add(tmp_path, "docker", available)


def test_raises_when_lockfile_has_no_template(tmp_path):
    (tmp_path / ".zenit.toml").write_text("[project]\naddons = []\n")
    available = [_make_addon("docker")]
    with pytest.raises(ZenitError, match="template"):
        check_can_add(tmp_path, "docker", available)


def test_raises_for_unknown_addon(tmp_path):
    _write_lock(tmp_path, "blank", [])
    available = [_make_addon("docker")]
    with pytest.raises(ZenitError, match="Unknown addon"):
        check_can_add(tmp_path, "nonexistent", available)


def test_raises_when_addon_already_installed(tmp_path):
    _write_lock(tmp_path, "blank", ["docker"])
    available = [_make_addon("docker")]
    with pytest.raises(ZenitError, match="already listed"):
        check_can_add(tmp_path, "docker", available)


def test_raises_when_dependency_missing(tmp_path):
    _write_lock(tmp_path, "blank", [])
    available = [_make_addon("redis"), _make_addon("celery", requires=["redis"])]
    with pytest.raises(ZenitError, match="requires"):
        check_can_add(tmp_path, "celery", available)


def test_passes_when_dependency_installed(tmp_path):
    _write_lock(tmp_path, "blank", ["redis"])
    available = [_make_addon("redis"), _make_addon("celery", requires=["redis"])]
    lockfile = check_can_add(tmp_path, "celery", available)
    assert lockfile.template == "blank"
    assert "redis" in lockfile.addons


def test_returns_lockfile_on_success(tmp_path):
    _write_lock(tmp_path, "fastapi", ["docker"])
    available = [_make_addon("docker"), _make_addon("redis")]
    lockfile = check_can_add(tmp_path, "redis", available)
    assert lockfile.template == "fastapi"
    assert lockfile.addons == ["docker"]


def test_raises_when_can_apply_returns_reason(tmp_path):
    _write_lock(tmp_path, "blank", [])

    class FakeModule:
        @staticmethod
        def can_apply(project_dir: Path, lockfile: object) -> str | None:
            return "Custom reason why it cannot apply."

    addon = _make_addon("docker")
    addon._module = FakeModule()
    available = [addon]

    with pytest.raises(ZenitError, match="Custom reason"):
        check_can_add(tmp_path, "docker", available)


def test_passes_when_can_apply_returns_none(tmp_path):
    _write_lock(tmp_path, "blank", [])

    class FakeModule:
        @staticmethod
        def can_apply(project_dir: Path, lockfile: object) -> str | None:
            return None

    addon = _make_addon("docker")
    addon._module = FakeModule()
    available = [addon]

    lockfile = check_can_add(tmp_path, "docker", available)
    assert lockfile.template == "blank"


def test_passes_when_no_can_apply_hook(tmp_path):
    _write_lock(tmp_path, "blank", [])
    available = [_make_addon("docker")]
    lockfile = check_can_add(tmp_path, "docker", available)
    assert lockfile is not None


def test_error_message_lists_known_addons_on_unknown(tmp_path):
    _write_lock(tmp_path, "blank", [])
    available = [_make_addon("docker"), _make_addon("redis")]
    with pytest.raises(ZenitError, match="docker"):
        check_can_add(tmp_path, "bogus", available)
