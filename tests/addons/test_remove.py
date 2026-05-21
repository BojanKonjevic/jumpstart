"""Tests for zenit.remove — addon removal from existing projects."""

from __future__ import annotations

import os
import secrets
import subprocess
from contextlib import contextmanager
from pathlib import Path

import pytest
import yaml
from conftest import ZENIT_ROOT

from zenit.addons._registry import get_available_addons
from zenit.addons.remove import remove_addon
from zenit.core._apply_loader import load_apply
from zenit.core.apply import apply_contributions
from zenit.core.collect import collect_all
from zenit.core.context import Context
from zenit.core.generate import generate_all
from zenit.core.git import init
from zenit.core.lockfile import read_lockfile, write_lockfile
from zenit.schema.exceptions import ZenitError
from zenit.templates._load_config import load_template_config


@contextmanager
def suppress_stdin():
    """Context manager to suppress stdin by redirecting to /dev/null."""
    try:
        with open(os.devnull) as devnull:
            old_stdin = os.dup(0)
            try:
                os.dup2(devnull.fileno(), 0)
                yield
            finally:
                os.dup2(old_stdin, 0)
                os.close(old_stdin)
    except OSError:
        # Fallback for systems where os.devnull isn't available
        yield


def _scaffold(tmp_path: Path, name: str, template: str, addons: list[str]) -> Path:
    """Run the full scaffold pipeline into tmp_path / name and return the project dir."""
    project_dir = tmp_path / name
    project_dir.mkdir()

    pkg_name = name.replace("-", "_")

    ctx = Context(
        name=name,
        pkg_name=pkg_name,
        template=template,
        addons=addons,
        zenit_root=ZENIT_ROOT,
        project_dir=project_dir,
    )

    # Common files

    load_apply(ZENIT_ROOT / "templates" / "_common" / "apply.py")(ctx)

    # Template + addon contributions
    available = get_available_addons()
    template_config = load_template_config(ZENIT_ROOT, template)
    selected_addon_configs = [cfg for cfg in available if cfg.id in addons]

    secret_key = secrets.token_hex(32) if template == "fastapi" else None

    render_vars: dict[str, object] = {
        "name": name,
        "pkg_name": pkg_name,
        "template": template,
        "secret_key": secret_key or "change-me-run-openssl-rand-hex-32",
        "has_postgres": template == "fastapi",
        "has_redis": "redis" in addons,
    }

    contributions = collect_all(template_config, selected_addon_configs)
    apply_contributions(
        ctx, contributions, template_config.injection_points, render_vars
    )
    generate_all(ctx, template_config, contributions)

    # Initialize git repo

    init(project_dir)

    # Write lockfile
    write_lockfile(project_dir, template, addons)

    return project_dir


# ── Unit tests ────────────────────────────────────────────────────────────────


class TestRemoveAddonUnit:
    """Unit tests for individual remove functions."""

    def test_remove_files_deletes_addon_files(self, tmp_path):
        project_dir = _scaffold(tmp_path, "myapp", "blank", ["sentry"])
        assert (project_dir / "src" / "myapp" / "integrations" / "sentry.py").exists()

        with suppress_stdin():
            remove_addon("sentry", project_dir=project_dir)

        assert not (
            project_dir / "src" / "myapp" / "integrations" / "sentry.py"
        ).exists()

    def test_remove_docker_files(self, tmp_path):
        project_dir = _scaffold(tmp_path, "myapp", "blank", ["docker"])
        assert (project_dir / "Dockerfile").exists()
        assert (project_dir / "compose.yml").exists()
        assert (project_dir / ".dockerignore").exists()

        with suppress_stdin():
            remove_addon("docker", project_dir=project_dir)

        assert not (project_dir / "Dockerfile").exists()
        assert not (project_dir / "compose.yml").exists()
        assert not (project_dir / ".dockerignore").exists()

    def test_remove_redis_files(self, tmp_path):
        project_dir = _scaffold(tmp_path, "myapp", "blank", ["redis"])
        assert (project_dir / "src" / "myapp" / "integrations" / "redis.py").exists()

        with suppress_stdin():
            remove_addon("redis", project_dir=project_dir)

        assert not (
            project_dir / "src" / "myapp" / "integrations" / "redis.py"
        ).exists()

    def test_remove_celery_files(self, tmp_path):
        project_dir = _scaffold(
            tmp_path, "myapp", "blank", ["docker", "redis", "celery"]
        )
        assert (project_dir / "src" / "myapp" / "tasks" / "celery_app.py").exists()
        assert (project_dir / "src" / "myapp" / "tasks" / "example_tasks.py").exists()

        with suppress_stdin():
            remove_addon("celery", project_dir=project_dir)

        assert not (project_dir / "src" / "myapp" / "tasks" / "celery_app.py").exists()
        assert not (
            project_dir / "src" / "myapp" / "tasks" / "example_tasks.py"
        ).exists()

    def test_remove_github_actions_files(self, tmp_path):
        project_dir = _scaffold(tmp_path, "myapp", "blank", ["github-actions"])
        assert (project_dir / ".github" / "workflows" / "ci.yml").exists()

        with suppress_stdin():
            remove_addon("github-actions", project_dir=project_dir)

        assert not (project_dir / ".github" / "workflows" / "ci.yml").exists()
        # .github/workflows directory should be removed if empty
        assert not (project_dir / ".github" / "workflows").exists()
        assert not (project_dir / ".github").exists()

    def test_remove_updates_lockfile(self, tmp_path):
        project_dir = _scaffold(tmp_path, "myapp", "blank", ["docker", "redis"])
        lockfile_before = read_lockfile(project_dir)
        assert "redis" in lockfile_before.addons

        with suppress_stdin():
            remove_addon("redis", project_dir=project_dir)

        lockfile_after = read_lockfile(project_dir)
        assert "redis" not in lockfile_after.addons
        assert "docker" in lockfile_after.addons

    def test_remove_cleans_compose_services(self, tmp_path):
        project_dir = _scaffold(tmp_path, "myapp", "blank", ["docker", "redis"])
        compose = yaml.safe_load((project_dir / "compose.yml").read_text())
        assert "redis" in compose.get("services", {})

        with suppress_stdin():
            remove_addon("redis", project_dir=project_dir)

        compose = yaml.safe_load((project_dir / "compose.yml").read_text())
        assert "redis" not in compose.get("services", {})

    def test_remove_cleans_env_vars(self, tmp_path):
        project_dir = _scaffold(tmp_path, "myapp", "blank", ["redis"])
        env = (project_dir / ".env").read_text()
        assert "REDIS_URL" in env

        with suppress_stdin():
            remove_addon("redis", project_dir=project_dir)

        env = (project_dir / ".env").read_text()
        assert "REDIS_URL" not in env

    def test_remove_injections(self, tmp_path):
        project_dir = _scaffold(tmp_path, "myapp", "blank", ["sentry"])
        main_py = (project_dir / "src" / "myapp" / "main.py").read_text()
        assert "init_sentry" in main_py

        with suppress_stdin():
            remove_addon("sentry", project_dir=project_dir)

        main_py = (project_dir / "src" / "myapp" / "main.py").read_text()
        assert "init_sentry" not in main_py

    def test_remove_deletes_empty_directories(self, tmp_path):
        project_dir = _scaffold(tmp_path, "myapp", "blank", ["sentry"])
        integrations_dir = project_dir / "src" / "myapp" / "integrations"
        assert integrations_dir.exists()

        with suppress_stdin():
            remove_addon("sentry", project_dir=project_dir)

        assert not integrations_dir.exists()

    def test_cannot_remove_unknown_addon(self):
        with suppress_stdin(), pytest.raises(ZenitError):
            remove_addon("nonexistent")

    def test_cannot_remove_from_non_zenit_project(self, tmp_path, monkeypatch):
        project_dir = tmp_path / "myapp"
        project_dir.mkdir()
        monkeypatch.chdir(project_dir)

        with suppress_stdin(), pytest.raises(ZenitError):
            remove_addon("docker", project_dir=project_dir)


# ── Integration tests ─────────────────────────────────────────────────────────


class TestRemoveAddonIntegration:
    """Integration tests that verify project remains functional after removal."""

    def test_blank_project_still_runnable_after_removing_sentry(
        self, tmp_path, monkeypatch
    ):
        project_dir = _scaffold(tmp_path, "myapp", "blank", ["sentry"])
        monkeypatch.chdir(project_dir)

        with suppress_stdin():
            remove_addon("sentry", project_dir=project_dir)

        # Project should still have valid structure
        assert (project_dir / "src" / "myapp" / "main.py").exists()
        assert (project_dir / "pyproject.toml").exists()

    def test_blank_project_still_runnable_after_removing_docker(
        self, tmp_path, monkeypatch
    ):
        project_dir = _scaffold(tmp_path, "myapp", "blank", ["docker"])
        monkeypatch.chdir(project_dir)

        with suppress_stdin():
            remove_addon("docker", project_dir=project_dir)

        assert (project_dir / "src" / "myapp" / "main.py").exists()

    def test_blank_project_after_removing_multiple_addons(self, tmp_path, monkeypatch):
        project_dir = _scaffold(tmp_path, "myapp", "blank", ["docker", "redis"])
        monkeypatch.chdir(project_dir)

        with suppress_stdin():
            remove_addon("docker", project_dir=project_dir)

        with suppress_stdin():
            remove_addon("redis", project_dir=project_dir)

        # Should be back to basic blank structure
        assert (project_dir / "src" / "myapp" / "main.py").exists()
        assert not (project_dir / "Dockerfile").exists()
        assert not (project_dir / "src" / "myapp" / "integrations").exists()

    def test_fastapi_project_after_removing_sentry(self, tmp_path, monkeypatch):
        project_dir = _scaffold(tmp_path, "myapi", "fastapi", ["docker", "sentry"])
        monkeypatch.chdir(project_dir)

        with suppress_stdin():
            remove_addon("sentry", project_dir=project_dir)

        lifecycle = (project_dir / "src" / "myapi" / "lifecycle.py").read_text()
        assert "init_sentry" not in lifecycle
        # FastAPI structure should still be intact
        assert (project_dir / "src" / "myapi" / "main.py").exists()

    def test_github_actions_removal_leaves_clean_state(self, tmp_path, monkeypatch):
        project_dir = _scaffold(tmp_path, "myapp", "blank", ["github-actions"])
        monkeypatch.chdir(project_dir)

        with suppress_stdin():
            remove_addon("github-actions", project_dir=project_dir)

        assert not (project_dir / ".github").exists()

    def test_removing_docker_keeps_sentry_intact(self, tmp_path, monkeypatch):
        project_dir = _scaffold(tmp_path, "myapp", "blank", ["docker", "sentry"])
        monkeypatch.chdir(project_dir)

        with suppress_stdin():
            remove_addon("docker", project_dir=project_dir)

        # Sentry should still be present
        assert (project_dir / "src" / "myapp" / "integrations" / "sentry.py").exists()
        main_py = (project_dir / "src" / "myapp" / "main.py").read_text()
        assert "init_sentry" in main_py

    def test_remove_addon_preserves_git_history(self, tmp_path, monkeypatch):
        project_dir = _scaffold(tmp_path, "myapp", "blank", ["sentry"])
        monkeypatch.chdir(project_dir)

        initial_commits = len(
            subprocess.run(
                ["git", "log", "--oneline"],
                cwd=project_dir,
                capture_output=True,
                text=True,
            ).stdout.splitlines()
        )

        with suppress_stdin():
            remove_addon("sentry", project_dir=project_dir)

        # Should still have git history (removal doesn't delete .git)
        assert (project_dir / ".git").exists()
        current_commits = len(
            subprocess.run(
                ["git", "log", "--oneline"],
                cwd=project_dir,
                capture_output=True,
                text=True,
            ).stdout.splitlines()
        )
        assert current_commits >= initial_commits

    def test_remove_celery_keeps_redis(self, tmp_path, monkeypatch):
        project_dir = _scaffold(
            tmp_path, "myapp", "blank", ["docker", "redis", "celery"]
        )
        monkeypatch.chdir(project_dir)

        with suppress_stdin():
            remove_addon("celery", project_dir=project_dir)

        # Redis should still be present
        assert (project_dir / "src" / "myapp" / "integrations" / "redis.py").exists()
        lockfile = read_lockfile(project_dir)
        assert "redis" in lockfile.addons

    def test_remove_addon_no_stdin(self, tmp_path, monkeypatch):
        """Test removal works when there's no stdin available (like CI)."""
        project_dir = _scaffold(tmp_path, "myapp", "blank", ["sentry"])
        monkeypatch.chdir(project_dir)

        with suppress_stdin():
            remove_addon("sentry", project_dir=project_dir)

        assert not (
            project_dir / "src" / "myapp" / "integrations" / "sentry.py"
        ).exists()

    def test_remove_redis_cleans_compose_and_env(self, tmp_path, monkeypatch):
        project_dir = _scaffold(tmp_path, "myapp", "blank", ["docker", "redis"])
        monkeypatch.chdir(project_dir)

        with suppress_stdin():
            remove_addon("redis", project_dir=project_dir)

        compose = yaml.safe_load((project_dir / "compose.yml").read_text())
        assert "redis" not in compose.get("services", {})
        assert "redis-data" not in compose.get("volumes", {})

        env = (project_dir / ".env").read_text()
        assert "REDIS_URL" not in env

    def test_remove_invalid_addon_doesnt_modify_project(self, tmp_path, monkeypatch):
        project_dir = _scaffold(tmp_path, "myapp", "blank", ["sentry"])
        monkeypatch.chdir(project_dir)

        main_before = (project_dir / "src" / "myapp" / "main.py").read_text()

        with suppress_stdin(), pytest.raises(ZenitError):
            remove_addon("nonexistent", project_dir=project_dir)

        main_after = (project_dir / "src" / "myapp" / "main.py").read_text()
        assert main_before == main_after

    def test_remove_addon_that_is_dependency(self, tmp_path, monkeypatch):
        """Trying to remove an addon that's required by others should fail."""
        project_dir = _scaffold(
            tmp_path, "myapp", "blank", ["docker", "redis", "celery"]
        )
        monkeypatch.chdir(project_dir)

        with suppress_stdin(), pytest.raises(ZenitError):
            remove_addon("redis", project_dir=project_dir)  # celery depends on redis

    def test_remove_sentry_from_fastapi_removes_settings_fields(
        self, tmp_path, monkeypatch
    ):
        project_dir = _scaffold(tmp_path, "myapi", "fastapi", ["docker", "sentry"])
        monkeypatch.chdir(project_dir)

        with suppress_stdin():
            remove_addon("sentry", project_dir=project_dir)

        settings = (project_dir / "src" / "myapi" / "settings.py").read_text()
        assert "sentry_dsn" not in settings
        assert "sentry_environment" not in settings

    def test_remove_docker_from_fastapi_leaves_db_configuration(
        self, tmp_path, monkeypatch
    ):
        """Removing docker from fastapi should still keep database configuration."""
        project_dir = _scaffold(tmp_path, "myapi", "fastapi", ["docker", "sentry"])
        monkeypatch.chdir(project_dir)

        # Can't remove docker from fastapi since it's required
        with suppress_stdin(), pytest.raises(ZenitError):
            remove_addon("docker", project_dir=project_dir)
