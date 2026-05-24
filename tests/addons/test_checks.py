"""Tests for zenit.checks — precondition checking for zenit add."""

from pathlib import Path

import pytest

from zenit.addons.checks import check_can_add
from zenit.core.lockfile import write_lockfile
from zenit.schema.exceptions import ZenitError
from zenit.schema.models import AddonConfig, AddonHooks, AddonMeta


def _make_addon_meta(id: str, requires: list[str] | None = None) -> AddonMeta:
    return AddonMeta(id=id, description=f"{id} addon", requires=requires or [])


def _make_addon_config(
    id: str, requires: list[str] | None = None, hooks: AddonHooks | None = None
) -> AddonConfig:
    cfg = AddonConfig(id=id, description=f"{id} addon", requires=requires or [])
    object.__setattr__(cfg, "_module", hooks)
    return cfg


def _write_lock(project_dir: Path, template: str, addons: list[str]) -> None:
    write_lockfile(project_dir, template, addons)


def _patch_registry(
    monkeypatch: pytest.MonkeyPatch,
    metas: list[AddonMeta],
    configs: dict[str, AddonConfig] | None = None,
) -> None:
    """Patch list_addons and get_addon to return controlled data.

    If *configs* is omitted (or missing an entry for a requested addon),
    a minimal AddonConfig is auto-generated from the matching meta so
    that hook-check callers don't break.
    """
    _configs = dict(configs or {})

    def _get_addon(addon_id: str) -> AddonConfig:
        if addon_id in _configs:
            return _configs[addon_id]
        meta = next(m for m in metas if m.id == addon_id)
        return AddonConfig(id=meta.id, description=meta.description)

    monkeypatch.setattr(
        "zenit.addons.checks.list_addons",
        lambda: metas,
    )
    monkeypatch.setattr(
        "zenit.addons.checks.get_addon",
        _get_addon,
    )


def test_raises_when_no_lockfile(tmp_path, monkeypatch):
    _patch_registry(monkeypatch, [_make_addon_meta("docker")])
    with pytest.raises(ZenitError, match=".zenit.toml"):
        check_can_add(tmp_path, "docker")


def test_raises_when_lockfile_has_no_template(tmp_path, monkeypatch):
    (tmp_path / ".zenit.toml").write_text("[project]\naddons = []\n")
    _patch_registry(monkeypatch, [_make_addon_meta("docker")])
    with pytest.raises(ZenitError, match="template"):
        check_can_add(tmp_path, "docker")


def test_raises_for_unknown_addon(tmp_path, monkeypatch):
    _write_lock(tmp_path, "blank", [])
    _patch_registry(monkeypatch, [_make_addon_meta("docker")])
    with pytest.raises(ZenitError, match="Unknown addon"):
        check_can_add(tmp_path, "nonexistent")


def test_raises_when_addon_already_installed(tmp_path, monkeypatch):
    _write_lock(tmp_path, "blank", ["docker"])
    _patch_registry(monkeypatch, [_make_addon_meta("docker")])
    with pytest.raises(ZenitError, match="already listed"):
        check_can_add(tmp_path, "docker")


def test_raises_when_dependency_missing(tmp_path, monkeypatch):
    _write_lock(tmp_path, "blank", [])
    metas = [_make_addon_meta("redis"), _make_addon_meta("celery", requires=["redis"])]
    _patch_registry(monkeypatch, metas)
    with pytest.raises(ZenitError, match="requires"):
        check_can_add(tmp_path, "celery")


def test_passes_when_dependency_installed(tmp_path, monkeypatch):
    _write_lock(tmp_path, "blank", ["redis"])
    metas = [_make_addon_meta("redis"), _make_addon_meta("celery", requires=["redis"])]
    _patch_registry(monkeypatch, metas)
    lockfile = check_can_add(tmp_path, "celery")
    assert lockfile.template == "blank"
    assert "redis" in lockfile.addons


def test_returns_lockfile_on_success(tmp_path, monkeypatch):
    _write_lock(tmp_path, "fastapi", ["docker"])
    metas = [_make_addon_meta("docker"), _make_addon_meta("redis")]
    _patch_registry(monkeypatch, metas)
    lockfile = check_can_add(tmp_path, "redis")
    assert lockfile.template == "fastapi"
    assert lockfile.addons == ["docker"]


def test_raises_when_can_apply_returns_reason(tmp_path, monkeypatch):
    _write_lock(tmp_path, "blank", [])

    class FakeHooks:
        @staticmethod
        def can_apply(project_dir: Path, lockfile: object) -> str | None:
            return "Custom reason why it cannot apply."

    cfg = _make_addon_config("docker", hooks=FakeHooks())
    _patch_registry(monkeypatch, [_make_addon_meta("docker")], {"docker": cfg})

    with pytest.raises(ZenitError, match="Custom reason"):
        check_can_add(tmp_path, "docker")


def test_passes_when_can_apply_returns_none(tmp_path, monkeypatch):
    _write_lock(tmp_path, "blank", [])

    class FakeHooks:
        @staticmethod
        def can_apply(project_dir: Path, lockfile: object) -> str | None:
            return None

    cfg = _make_addon_config("docker", hooks=FakeHooks())
    _patch_registry(monkeypatch, [_make_addon_meta("docker")], {"docker": cfg})

    lockfile = check_can_add(tmp_path, "docker")
    assert lockfile.template == "blank"


def test_passes_when_no_can_apply_hook(tmp_path, monkeypatch):
    _write_lock(tmp_path, "blank", [])
    cfg = _make_addon_config("docker")
    _patch_registry(monkeypatch, [_make_addon_meta("docker")], {"docker": cfg})
    lockfile = check_can_add(tmp_path, "docker")
    assert lockfile is not None


def test_error_message_lists_known_addons_on_unknown(tmp_path, monkeypatch):
    _write_lock(tmp_path, "blank", [])
    metas = [_make_addon_meta("docker"), _make_addon_meta("redis")]
    _patch_registry(monkeypatch, metas)
    with pytest.raises(ZenitError, match="docker"):
        check_can_add(tmp_path, "bogus")
