"""Tests for zenit.validate — name validation, preflight checks,
and addon dependency/template-compatibility validation.
"""

from __future__ import annotations

import shutil
from unittest.mock import patch

import pytest
from conftest import ExitAssertion

from zenit.core.validate import check_preflight, validate_addon_deps, validate_name
from zenit.schema.models import AddonConfig

# ── helpers ───────────────────────────────────────────────────────────────────


def _assert_exits(fn, *args, **kwargs) -> None:
    with ExitAssertion():
        fn(*args, **kwargs)


def _make_addon(
    id: str,
    requires: list[str] | None = None,
    templates: list[str] | None = None,
) -> AddonConfig:
    return AddonConfig(
        id=id,
        description="",
        requires=requires or [],
        templates=templates or [],
    )


# ── validate_name — acceptance ────────────────────────────────────────────────


def test_validate_name_accepts_simple_name(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    validate_name("my-project", "my_project")


def test_validate_name_accepts_underscores(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    validate_name("my_project", "my_project")


def test_validate_name_accepts_alphanumeric(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    validate_name("project123", "project123")


def test_validate_name_accepts_single_letter(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    validate_name("x", "x")


def test_validate_name_accepts_mixed_case(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    validate_name("MyProject", "MyProject")


# ── validate_name — rejection ─────────────────────────────────────────────────


def test_validate_name_rejects_existing_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "myproject").mkdir()
    _assert_exits(validate_name, "myproject", "myproject")


def test_validate_name_rejects_leading_digit(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _assert_exits(validate_name, "1project", "1project")


def test_validate_name_rejects_hyphen_start(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _assert_exits(validate_name, "-project", "_project")


def test_validate_name_rejects_special_characters(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _assert_exits(validate_name, "my project", "my project")


def test_validate_name_rejects_dot(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _assert_exits(validate_name, "my.project", "my.project")


def test_validate_name_rejects_slash(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _assert_exits(validate_name, "my/project", "my/project")


def test_validate_name_rejects_empty_string(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _assert_exits(validate_name, "", "")


def test_validate_name_rejects_stdlib_module_json(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _assert_exits(validate_name, "json", "json")


def test_validate_name_rejects_stdlib_module_os(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _assert_exits(validate_name, "os", "os")


def test_validate_name_rejects_stdlib_module_sys(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _assert_exits(validate_name, "sys", "sys")


def test_validate_name_rejects_stdlib_module_typing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _assert_exits(validate_name, "typing", "typing")


# ── validate_addon_deps — acceptance ─────────────────────────────────────────


def test_validate_addon_deps_passes_when_all_satisfied():
    available = [
        _make_addon("redis"),
        _make_addon("celery", requires=["redis"]),
    ]
    validate_addon_deps(["redis", "celery"], available)


def test_validate_addon_deps_passes_with_no_addons():
    available = [_make_addon("redis"), _make_addon("celery", requires=["redis"])]
    validate_addon_deps([], available)


def test_validate_addon_deps_passes_with_no_requirements():
    available = [_make_addon("docker"), _make_addon("github-actions")]
    validate_addon_deps(["docker", "github-actions"], available)


def test_validate_addon_deps_passes_single_addon_no_requires():
    available = [_make_addon("sentry")]
    validate_addon_deps(["sentry"], available)


def test_validate_addon_deps_passes_compatible_template():
    available = [_make_addon("auth-manual", templates=["fastapi"])]
    validate_addon_deps(["auth-manual"], available, template="fastapi")


def test_validate_addon_deps_passes_addon_with_no_template_restriction():
    available = [_make_addon("docker", templates=[])]
    validate_addon_deps(["docker"], available, template="blank")


def test_validate_addon_deps_passes_addon_with_no_template_restriction_fastapi():
    available = [_make_addon("docker", templates=[])]
    validate_addon_deps(["docker"], available, template="fastapi")


# ── validate_addon_deps — rejection ──────────────────────────────────────────


def test_validate_addon_deps_fails_when_requirement_missing():
    available = [
        _make_addon("redis"),
        _make_addon("celery", requires=["redis"]),
    ]
    _assert_exits(validate_addon_deps, ["celery"], available)


def test_validate_addon_deps_fails_for_transitive_missing():
    available = [
        _make_addon("redis"),
        _make_addon("celery", requires=["redis"]),
        _make_addon("docker"),
    ]
    _assert_exits(validate_addon_deps, ["docker", "celery"], available)


def test_validate_addon_deps_fails_template_incompatible():
    available = [_make_addon("auth-manual", templates=["fastapi"])]
    _assert_exits(validate_addon_deps, ["auth-manual"], available, template="blank")


def test_validate_addon_deps_fails_template_incompatible_wrong_template():
    available = [_make_addon("auth-manual", templates=["fastapi"])]
    _assert_exits(
        validate_addon_deps, ["auth-manual"], available, template="other-template"
    )


def test_validate_addon_deps_template_check_before_dep_check():
    # auth-manual is fastapi-only AND requires some dep — template error should fire
    available = [
        _make_addon("dep"),
        _make_addon("auth-manual", requires=["dep"], templates=["fastapi"]),
    ]
    _assert_exits(validate_addon_deps, ["auth-manual"], available, template="blank")


def test_validate_addon_deps_fails_with_multiple_missing_deps():
    available = [
        _make_addon("a"),
        _make_addon("b"),
        _make_addon("c", requires=["a", "b"]),
    ]
    # Only "c" selected — both "a" and "b" are missing
    _assert_exits(validate_addon_deps, ["c"], available)


# ── check_preflight — tools present ──────────────────────────────────────────


def test_check_preflight_passes_when_tools_available():
    # uv and git are available in the test environment
    if not shutil.which("uv") or not shutil.which("git"):
        pytest.skip("uv or git not available in this environment")
    check_preflight()  # should not raise


def test_check_preflight_fails_when_uv_missing():
    with (
        patch("shutil.which", side_effect=lambda cmd: None if cmd == "uv" else cmd),
        ExitAssertion(),
    ):
        check_preflight()


def test_check_preflight_fails_when_git_missing():
    with (
        patch(
            "shutil.which",
            side_effect=lambda cmd: None if cmd == "git" else "/usr/bin/" + cmd,
        ),
        ExitAssertion(),
    ):
        check_preflight()


def test_check_preflight_fails_when_both_missing():
    with patch("shutil.which", return_value=None), ExitAssertion():
        check_preflight()
