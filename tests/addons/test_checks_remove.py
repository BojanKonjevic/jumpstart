"""Tests for zenit.checks_remove — precondition checking for zenit remove.

Mirrors the structure of test_checks.py.  Every public failure path in
check_can_remove gets its own test; the happy path verifies the returned
lockfile is correct.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from zenit.addons.checks_remove import check_can_remove
from zenit.core.lockfile import write_lockfile
from zenit.schema.exceptions import ZenitError
from zenit.schema.models import AddonConfig

# ── helpers ───────────────────────────────────────────────────────────────────


def _make_addon(
    id: str,
    requires: list[str] | None = None,
    templates: list[str] | None = None,
) -> AddonConfig:
    return AddonConfig(
        id=id,
        description=f"{id} addon",
        requires=requires or [],
        templates=templates or [],
    )


def _write_lock(project_dir: Path, template: str, addons: list[str]) -> None:
    write_lockfile(project_dir, template, addons)


# ── lockfile checks ───────────────────────────────────────────────────────────


def test_raises_when_no_lockfile(tmp_path):
    available = [_make_addon("docker")]
    with pytest.raises(ZenitError, match=".zenit.toml"):
        check_can_remove(tmp_path, "docker", available)


def test_raises_when_lockfile_has_no_template(tmp_path):
    (tmp_path / ".zenit.toml").write_text("[project]\naddons = []\n")
    available = [_make_addon("docker")]
    with pytest.raises(ZenitError, match="template"):
        check_can_remove(tmp_path, "docker", available)


# ── addon existence ───────────────────────────────────────────────────────────


def test_raises_for_unknown_addon(tmp_path):
    _write_lock(tmp_path, "blank", ["docker"])
    available = [_make_addon("docker")]
    with pytest.raises(ZenitError, match="Unknown addon"):
        check_can_remove(tmp_path, "nonexistent", available)


def test_error_message_lists_known_addons_on_unknown(tmp_path):
    _write_lock(tmp_path, "blank", ["docker"])
    available = [_make_addon("docker"), _make_addon("redis")]
    with pytest.raises(ZenitError, match="docker"):
        check_can_remove(tmp_path, "bogus", available)


# ── not installed check ───────────────────────────────────────────────────────


def test_raises_when_addon_not_installed(tmp_path):
    _write_lock(tmp_path, "blank", ["docker"])
    available = [_make_addon("docker"), _make_addon("redis")]
    with pytest.raises(ZenitError, match="not listed"):
        check_can_remove(tmp_path, "redis", available)


def test_raises_when_addons_list_is_empty(tmp_path):
    _write_lock(tmp_path, "blank", [])
    available = [_make_addon("docker")]
    with pytest.raises(ZenitError, match="not listed"):
        check_can_remove(tmp_path, "docker", available)


# ── dependent addon check ─────────────────────────────────────────────────────


def test_raises_when_another_addon_depends_on_it(tmp_path):
    _write_lock(tmp_path, "blank", ["redis", "celery"])
    available = [
        _make_addon("redis"),
        _make_addon("celery", requires=["redis"]),
    ]
    with pytest.raises(ZenitError, match="celery"):
        check_can_remove(tmp_path, "redis", available)


def test_error_message_names_all_dependents(tmp_path):
    _write_lock(tmp_path, "blank", ["redis", "celery", "worker"])
    available = [
        _make_addon("redis"),
        _make_addon("celery", requires=["redis"]),
        _make_addon("worker", requires=["redis"]),
    ]
    with pytest.raises(ZenitError) as exc_info:
        check_can_remove(tmp_path, "redis", available)
    msg = str(exc_info.value)
    assert "celery" in msg
    assert "worker" in msg


def test_passes_when_dependent_is_not_installed(tmp_path):
    # celery depends on redis but celery is not installed
    _write_lock(tmp_path, "blank", ["redis"])
    available = [
        _make_addon("redis"),
        _make_addon("celery", requires=["redis"]),
    ]
    lockfile = check_can_remove(tmp_path, "redis", available)
    assert lockfile.template == "blank"


# ── template-required addon check ─────────────────────────────────────────────


def test_raises_when_template_requires_addon(tmp_path):
    # fastapi template requires docker — docker cannot be removed
    _write_lock(tmp_path, "fastapi", ["docker"])
    available = [_make_addon("docker")]
    with pytest.raises(ZenitError, match="required by the 'fastapi' template"):
        check_can_remove(tmp_path, "docker", available)


def test_passes_when_addon_not_required_by_template(tmp_path):
    _write_lock(tmp_path, "fastapi", ["docker", "redis"])
    available = [_make_addon("docker"), _make_addon("redis")]
    lockfile = check_can_remove(tmp_path, "redis", available)
    assert "redis" in lockfile.addons


def test_passes_for_blank_template_no_required_addons(tmp_path):
    _write_lock(tmp_path, "blank", ["docker"])
    available = [_make_addon("docker")]
    lockfile = check_can_remove(tmp_path, "docker", available)
    assert lockfile.template == "blank"


# ── can_remove hook ───────────────────────────────────────────────────────────


def test_raises_when_can_remove_returns_reason(tmp_path):
    _write_lock(tmp_path, "blank", ["docker"])

    class FakeHooks:
        @staticmethod
        def can_remove(project_dir: Path, lockfile: object) -> str | None:
            return "Custom reason why it cannot be removed."

    addon = _make_addon("docker")
    addon._module = FakeHooks()
    available = [addon]

    with pytest.raises(ZenitError, match="Custom reason"):
        check_can_remove(tmp_path, "docker", available)


def test_passes_when_can_remove_returns_none(tmp_path):
    _write_lock(tmp_path, "blank", ["docker"])

    class FakeHooks:
        @staticmethod
        def can_remove(project_dir: Path, lockfile: object) -> str | None:
            return None

    addon = _make_addon("docker")
    addon._module = FakeHooks()
    available = [addon]

    lockfile = check_can_remove(tmp_path, "docker", available)
    assert lockfile.template == "blank"


def test_passes_when_no_can_remove_hook(tmp_path):
    _write_lock(tmp_path, "blank", ["docker"])
    available = [_make_addon("docker")]
    lockfile = check_can_remove(tmp_path, "docker", available)
    assert lockfile is not None


def test_can_remove_hook_receives_correct_project_dir(tmp_path):
    _write_lock(tmp_path, "blank", ["docker"])
    received: list[Path] = []

    class FakeHooks:
        @staticmethod
        def can_remove(project_dir: Path, lockfile: object) -> str | None:
            received.append(project_dir)
            return None

    addon = _make_addon("docker")
    addon._module = FakeHooks()
    check_can_remove(tmp_path, "docker", [addon])
    assert received == [tmp_path]


# ── happy path — return value ─────────────────────────────────────────────────


def test_returns_lockfile_on_success(tmp_path):
    _write_lock(tmp_path, "fastapi", ["docker", "redis"])
    available = [_make_addon("docker"), _make_addon("redis")]
    lockfile = check_can_remove(tmp_path, "redis", available)
    assert lockfile.template == "fastapi"
    assert "docker" in lockfile.addons
    assert "redis" in lockfile.addons


def test_returns_lockfile_with_correct_addons(tmp_path):
    _write_lock(tmp_path, "blank", ["docker", "sentry", "github-actions"])
    available = [
        _make_addon("docker"),
        _make_addon("sentry"),
        _make_addon("github-actions"),
    ]
    lockfile = check_can_remove(tmp_path, "sentry", available)
    assert set(lockfile.addons) == {"docker", "sentry", "github-actions"}


def test_passes_removing_last_addon(tmp_path):
    _write_lock(tmp_path, "blank", ["sentry"])
    available = [_make_addon("sentry")]
    lockfile = check_can_remove(tmp_path, "sentry", available)
    assert lockfile.addons == ["sentry"]


# ── multiple checks compose correctly ────────────────────────────────────────


def test_raises_lockfile_check_before_dependent_check(tmp_path):
    # No lockfile at all — should raise on lockfile, not dependent check
    available = [_make_addon("redis"), _make_addon("celery", requires=["redis"])]
    with pytest.raises(ZenitError, match=".zenit.toml"):
        check_can_remove(tmp_path, "redis", available)


def test_raises_installed_check_before_dependent_check(tmp_path):
    # redis not installed — should raise "not listed", not "required by celery"
    _write_lock(tmp_path, "blank", ["celery"])
    available = [
        _make_addon("redis"),
        _make_addon("celery", requires=["redis"]),
    ]
    with pytest.raises(ZenitError, match="not listed"):
        check_can_remove(tmp_path, "redis", available)
