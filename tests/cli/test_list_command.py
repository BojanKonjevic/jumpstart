"""Functional tests for `zenit list`."""

from __future__ import annotations

from unittest.mock import patch

from typer.testing import CliRunner

from zenit.cli.main import app
from zenit.core.lockfile import ZenitLockfile

runner = CliRunner()

_PATCH = "zenit.cli.main.read_lockfile"


# ── Helpers ───────────────────────────────────────────────────────────────────


def _lockfile(
    template: str = "fastapi", addons: list[str] | None = None
) -> ZenitLockfile:
    return ZenitLockfile(
        template=template,
        addons=addons or [],
        zenit_version="1.0.0",
        schema_version=2,
    )


# ── --available ────────────────────────────────────────────────────────────────


def test_available_shows_templates_and_addons() -> None:
    result = runner.invoke(app, ["list", "--available"])
    assert result.exit_code == 0
    assert "Templates" in result.output
    assert "blank" in result.output
    assert "fastapi" in result.output
    assert "Addons" in result.output
    assert "docker" in result.output


def test_available_works_outside_project() -> None:
    with patch(_PATCH, return_value=None):
        result = runner.invoke(app, ["list", "--available"])
    assert result.exit_code == 0
    assert "Templates" in result.output


def test_available_shows_template_restriction_for_auth_manual() -> None:
    result = runner.invoke(app, ["list", "--available"])
    assert result.exit_code == 0
    assert "fastapi only" in result.output


# ── --installed ────────────────────────────────────────────────────────────────


def test_installed_shows_project_info() -> None:
    lf = _lockfile(template="fastapi", addons=["docker", "redis"])
    with patch(_PATCH, return_value=lf):
        result = runner.invoke(app, ["list", "--installed"])
    assert result.exit_code == 0
    assert "fastapi" in result.output
    assert "docker" in result.output
    assert "redis" in result.output
    assert "zenit 1.0.0" in result.output


def test_installed_shows_no_addons_message_when_empty() -> None:
    lf = _lockfile(template="blank", addons=[])
    with patch(_PATCH, return_value=lf):
        result = runner.invoke(app, ["list", "--installed"])
    assert result.exit_code == 0
    assert "No addons installed" in result.output


def test_installed_errors_outside_project() -> None:
    with patch(_PATCH, return_value=None):
        result = runner.invoke(app, ["list", "--installed"])
    assert result.exit_code == 1
    assert "No .zenit.toml found" in result.output


# ── mutually exclusive flags ───────────────────────────────────────────────────


def test_available_and_installed_are_mutually_exclusive() -> None:
    result = runner.invoke(app, ["list", "--available", "--installed"])
    assert result.exit_code == 1
    assert "mutually exclusive" in result.output


# ── default (no flags) ────────────────────────────────────────────────────────


def test_default_inside_project_shows_installed_and_available() -> None:
    lf = _lockfile(template="fastapi", addons=["docker"])
    with patch(_PATCH, return_value=lf):
        result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    assert "Installed" in result.output
    assert "docker" in result.output
    assert "Available to add" in result.output
    available_section = result.output.split("Available to add")[-1]
    assert "docker" not in available_section


def test_default_outside_project_behaves_as_available() -> None:
    with patch(_PATCH, return_value=None):
        result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    assert "Templates" in result.output
    assert "Addons" in result.output
    assert "Installed" not in result.output


def test_default_hides_incompatible_addons_for_template() -> None:
    lf = _lockfile(template="blank", addons=[])
    with patch(_PATCH, return_value=lf):
        result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    available_section = (
        result.output.split("Available to add")[-1]
        if "Available to add" in result.output
        else ""
    )
    assert "auth-manual" not in available_section


def test_default_all_addons_installed_shows_message() -> None:
    from zenit.addons._registry import get_available_addons

    all_ids = [a.id for a in get_available_addons()]
    lf = _lockfile(template="fastapi", addons=all_ids)
    with patch(_PATCH, return_value=lf):
        result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    assert "All available addons are already installed" in result.output


def test_default_shows_dependency_status_for_available_addons() -> None:
    lf = _lockfile(template="fastapi", addons=["docker", "redis"])
    with patch(_PATCH, return_value=lf):
        result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    assert "installed" in result.output
