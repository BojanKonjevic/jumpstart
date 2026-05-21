"""CLI-level tests for ``zenit create`` with non-interactive flags."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from zenit.cli.main import app

runner = CliRunner()


def test_create_with_template_flag(tmp_path: Path, monkeypatch) -> None:
    """--template fastapi selects the template without interactive picker."""
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app,
        ["create", "myproj", "--template", "fastapi", "--dry-run"],
        input="\n",
    )
    assert result.exit_code == 0
    assert "fastapi" in result.output


def test_create_with_invalid_template() -> None:
    """--template invalid exits with error."""
    result = runner.invoke(app, ["create", "myproj", "--template", "nope"])
    assert result.exit_code == 1
    assert "Unknown template" in result.output


def test_create_with_addons_flag(tmp_path: Path, monkeypatch) -> None:
    """--addons redis,celery selects multiple addons without interactive picker."""
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app,
        [
            "create",
            "myproj",
            "--template",
            "fastapi",
            "--addons",
            "redis,celery",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0
    assert "redis" in result.output
    assert "celery" in result.output


def test_create_with_invalid_addon() -> None:
    """--addons bogus exits with error."""
    result = runner.invoke(
        app, ["create", "myproj", "--template", "fastapi", "--addons", "bogus"]
    )
    assert result.exit_code == 1
    assert "Unknown addon" in result.output


def test_create_with_all_flags(tmp_path: Path, monkeypatch) -> None:
    """All flags together (template + addons + yes + dry-run)."""
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app,
        [
            "create",
            "myproj",
            "--template",
            "fastapi",
            "--addons",
            "docker,redis",
            "--yes",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0
    assert "fastapi" in result.output
    assert "docker" in result.output
    assert "redis" in result.output


def test_create_with_yes_alone(tmp_path: Path, monkeypatch) -> None:
    """--yes alone skips confirmation (template/addon use fallback prompts)."""
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app,
        ["create", "myproj", "--template", "blank", "--yes", "--dry-run"],
        input="\n",
    )
    assert result.exit_code == 0


def test_create_with_dry_run_and_flags(tmp_path: Path, monkeypatch) -> None:
    """--dry-run with --template and --addons shows preview without writing."""
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app,
        [
            "create",
            "myproj",
            "--template",
            "fastapi",
            "--addons",
            "docker,sentry",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0
    assert "Dry run" in result.output
    assert not (tmp_path / "myproj").exists()


def test_create_addon_dependency_validation() -> None:
    """--addons celery without its dependency redis exits with error."""
    result = runner.invoke(
        app,
        ["create", "myproj", "--template", "fastapi", "--addons", "celery"],
    )
    assert result.exit_code == 1
    assert "requires" in result.output
    assert "redis" in result.output


def test_create_multiple_addons_resolves_deps(tmp_path: Path, monkeypatch) -> None:
    """--addons redis,celery passes validation (celery requires redis)."""
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app,
        [
            "create",
            "myproj",
            "--template",
            "blank",
            "--addons",
            "docker,redis,celery",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0
    assert "celery" in result.output
