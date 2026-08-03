"""Tests for :func:`check_can_remove` - precondition checking for zenit remove.

Mirrors the structure of test_checks.py.  Every public failure path in
check_can_remove gets its own test; the happy path verifies the returned
lockfile is correct.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from zenit.addons.checks import check_can_remove
from zenit.core.lockfile import write_lockfile
from zenit.schema.exceptions import ZenitError
from zenit.schema.models import AddonConfig, AddonHooks, AddonMeta

# ── helpers ───────────────────────────────────────────────────────────────────


def _make_addon_meta(
    id: str,
    requires: list[str] | None = None,
    templates: list[str] | None = None,
) -> AddonMeta:
    return AddonMeta(
        id=id,
        description=f"{id} addon",
        requires=requires or [],
        templates=templates or [],
    )


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


# ── lockfile checks ───────────────────────────────────────────────────────────


def test_raises_when_no_lockfile(tmp_path, monkeypatch):
    _patch_registry(monkeypatch, [_make_addon_meta("docker")])
    with pytest.raises(ZenitError, match=".zenit.toml"):
        check_can_remove(tmp_path, "docker")


def test_raises_when_lockfile_has_no_template(tmp_path, monkeypatch):
    (tmp_path / ".zenit.toml").write_text("[project]\naddons = []\n")
    _patch_registry(monkeypatch, [_make_addon_meta("docker")])
    with pytest.raises(ZenitError, match="template"):
        check_can_remove(tmp_path, "docker")


# ── addon existence ───────────────────────────────────────────────────────────


def test_raises_for_unknown_addon(tmp_path, monkeypatch):
    _write_lock(tmp_path, "blank", ["docker"])
    _patch_registry(monkeypatch, [_make_addon_meta("docker")])
    with pytest.raises(ZenitError, match="Unknown addon"):
        check_can_remove(tmp_path, "nonexistent")


def test_error_message_lists_known_addons_on_unknown(tmp_path, monkeypatch):
    _write_lock(tmp_path, "blank", ["docker"])
    metas = [_make_addon_meta("docker"), _make_addon_meta("redis")]
    _patch_registry(monkeypatch, metas)
    with pytest.raises(ZenitError, match="docker"):
        check_can_remove(tmp_path, "bogus")


# ── not installed check ───────────────────────────────────────────────────────


def test_raises_when_addon_not_installed(tmp_path, monkeypatch):
    _write_lock(tmp_path, "blank", ["docker"])
    metas = [_make_addon_meta("docker"), _make_addon_meta("redis")]
    _patch_registry(monkeypatch, metas)
    with pytest.raises(ZenitError, match="not listed"):
        check_can_remove(tmp_path, "redis")


def test_raises_when_addons_list_is_empty(tmp_path, monkeypatch):
    _write_lock(tmp_path, "blank", [])
    _patch_registry(monkeypatch, [_make_addon_meta("docker")])
    with pytest.raises(ZenitError, match="not listed"):
        check_can_remove(tmp_path, "docker")


# ── dependent addon check ─────────────────────────────────────────────────────


def test_raises_when_another_addon_depends_on_it(tmp_path, monkeypatch):
    _write_lock(tmp_path, "blank", ["redis", "celery"])
    metas = [
        _make_addon_meta("redis"),
        _make_addon_meta("celery", requires=["redis"]),
    ]
    _patch_registry(monkeypatch, metas)
    with pytest.raises(ZenitError, match="celery"):
        check_can_remove(tmp_path, "redis")


def test_error_message_names_all_dependents(tmp_path, monkeypatch):
    _write_lock(tmp_path, "blank", ["redis", "celery", "worker"])
    metas = [
        _make_addon_meta("redis"),
        _make_addon_meta("celery", requires=["redis"]),
        _make_addon_meta("worker", requires=["redis"]),
    ]
    _patch_registry(monkeypatch, metas)
    with pytest.raises(ZenitError) as exc_info:
        check_can_remove(tmp_path, "redis")
    msg = str(exc_info.value)
    assert "celery" in msg
    assert "worker" in msg


def test_passes_when_dependent_is_not_installed(tmp_path, monkeypatch):
    _write_lock(tmp_path, "blank", ["redis"])
    metas = [
        _make_addon_meta("redis"),
        _make_addon_meta("celery", requires=["redis"]),
    ]
    _patch_registry(monkeypatch, metas)
    lockfile = check_can_remove(tmp_path, "redis")
    assert lockfile.template == "blank"


# ── template-required addon check ─────────────────────────────────────────────


def test_passes_when_no_template_requires_addon(tmp_path, monkeypatch):
    _write_lock(tmp_path, "fastapi", ["docker"])
    _patch_registry(monkeypatch, [_make_addon_meta("docker")])
    lockfile = check_can_remove(tmp_path, "docker")
    assert lockfile.template == "fastapi"


def test_passes_when_addon_not_required_by_template(tmp_path, monkeypatch):
    _write_lock(tmp_path, "fastapi", ["docker", "redis"])
    metas = [_make_addon_meta("docker"), _make_addon_meta("redis")]
    _patch_registry(monkeypatch, metas)
    lockfile = check_can_remove(tmp_path, "redis")
    assert "redis" in lockfile.addons


def test_passes_for_blank_template_no_required_addons(tmp_path, monkeypatch):
    _write_lock(tmp_path, "blank", ["docker"])
    _patch_registry(monkeypatch, [_make_addon_meta("docker")])
    lockfile = check_can_remove(tmp_path, "docker")
    assert lockfile.template == "blank"


# ── can_remove hook ───────────────────────────────────────────────────────────


def test_raises_when_can_remove_returns_reason(tmp_path, monkeypatch):
    _write_lock(tmp_path, "blank", ["docker"])

    class FakeHooks:
        @staticmethod
        def can_remove(project_dir: Path, lockfile: object) -> str | None:
            return "Custom reason why it cannot be removed."

    cfg = _make_addon_config("docker", hooks=FakeHooks())
    _patch_registry(monkeypatch, [_make_addon_meta("docker")], {"docker": cfg})

    with pytest.raises(ZenitError, match="Custom reason"):
        check_can_remove(tmp_path, "docker")


def test_passes_when_can_remove_returns_none(tmp_path, monkeypatch):
    _write_lock(tmp_path, "blank", ["docker"])

    class FakeHooks:
        @staticmethod
        def can_remove(project_dir: Path, lockfile: object) -> str | None:
            return None

    cfg = _make_addon_config("docker", hooks=FakeHooks())
    _patch_registry(monkeypatch, [_make_addon_meta("docker")], {"docker": cfg})

    lockfile = check_can_remove(tmp_path, "docker")
    assert lockfile.template == "blank"


def test_passes_when_no_can_remove_hook(tmp_path, monkeypatch):
    _write_lock(tmp_path, "blank", ["docker"])
    cfg = _make_addon_config("docker")
    _patch_registry(monkeypatch, [_make_addon_meta("docker")], {"docker": cfg})
    lockfile = check_can_remove(tmp_path, "docker")
    assert lockfile is not None


def test_can_remove_hook_receives_correct_project_dir(tmp_path, monkeypatch):
    _write_lock(tmp_path, "blank", ["docker"])
    received: list[Path] = []

    class FakeHooks:
        @staticmethod
        def can_remove(project_dir: Path, lockfile: object) -> str | None:
            received.append(project_dir)
            return None

    cfg = _make_addon_config("docker", hooks=FakeHooks())
    _patch_registry(monkeypatch, [_make_addon_meta("docker")], {"docker": cfg})
    check_can_remove(tmp_path, "docker")
    assert received == [tmp_path]


# ── happy path - return value ─────────────────────────────────────────────────


def test_returns_lockfile_on_success(tmp_path, monkeypatch):
    _write_lock(tmp_path, "fastapi", ["docker", "redis"])
    metas = [_make_addon_meta("docker"), _make_addon_meta("redis")]
    _patch_registry(monkeypatch, metas)
    lockfile = check_can_remove(tmp_path, "redis")
    assert lockfile.template == "fastapi"
    assert "docker" in lockfile.addons
    assert "redis" in lockfile.addons


def test_returns_lockfile_with_correct_addons(tmp_path, monkeypatch):
    _write_lock(tmp_path, "blank", ["docker", "sentry", "github-actions"])
    metas = [
        _make_addon_meta("docker"),
        _make_addon_meta("sentry"),
        _make_addon_meta("github-actions"),
    ]
    _patch_registry(monkeypatch, metas)
    lockfile = check_can_remove(tmp_path, "sentry")
    assert set(lockfile.addons) == {"docker", "sentry", "github-actions"}


def test_passes_removing_last_addon(tmp_path, monkeypatch):
    _write_lock(tmp_path, "blank", ["sentry"])
    _patch_registry(monkeypatch, [_make_addon_meta("sentry")])
    lockfile = check_can_remove(tmp_path, "sentry")
    assert lockfile.addons == ["sentry"]


# ── multiple checks compose correctly ────────────────────────────────────────


def test_raises_lockfile_check_before_dependent_check(tmp_path, monkeypatch):
    metas = [_make_addon_meta("redis"), _make_addon_meta("celery", requires=["redis"])]
    _patch_registry(monkeypatch, metas)
    with pytest.raises(ZenitError, match=".zenit.toml"):
        check_can_remove(tmp_path, "redis")


def test_raises_installed_check_before_dependent_check(tmp_path, monkeypatch):
    _write_lock(tmp_path, "blank", ["celery"])
    metas = [
        _make_addon_meta("redis"),
        _make_addon_meta("celery", requires=["redis"]),
    ]
    _patch_registry(monkeypatch, metas)
    with pytest.raises(ZenitError, match="not listed"):
        check_can_remove(tmp_path, "redis")
