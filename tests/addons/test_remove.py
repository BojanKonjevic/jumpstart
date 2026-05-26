"""Tests for zenit.remove — addon removal from existing projects."""

from __future__ import annotations

import os
import subprocess
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest
import typer
import yaml
from helpers import ZENIT_ROOT, write_test_manifest

from zenit.addons._registry import get_available_addons
from zenit.addons.remove import _remove_files, remove_addon
from zenit.core._apply_loader import load_apply
from zenit.core.apply import apply_contributions
from zenit.core.collect import collect_all
from zenit.core.context import Context
from zenit.core.filesystem import RealFileSystem
from zenit.core.generate import generate_all
from zenit.core.git import init
from zenit.core.lockfile import read_lockfile, write_lockfile
from zenit.core.manifest import read_manifest, write_manifest
from zenit.core.render import build_render_vars
from zenit.schema.exceptions import ZenitError
from zenit.schema.models import AddonConfig, FileContribution
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
    fs = RealFileSystem(project_dir)

    # Common files

    load_apply(ZENIT_ROOT / "templates" / "_common" / "apply.py")(ctx, fs)

    # Template + addon contributions
    available = get_available_addons()
    template_config = load_template_config(ZENIT_ROOT, template)
    selected_addon_configs = [cfg for cfg in available if cfg.id in addons]

    render_vars = build_render_vars(
        name=name,
        pkg_name=pkg_name,
        template=template,
        addons=addons,
    )

    contributions = collect_all(template_config, selected_addon_configs)
    apply_contributions(
        ctx, fs, contributions, template_config.injection_points, render_vars
    )
    generate_all(ctx, fs, contributions)
    write_test_manifest(project_dir, addons, render_vars)

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
        # Docker owns compose entries but _refresh_compose reconciles
        # compose.yml based on currently installed addons.
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

    def test_empty_init_py_kept_when_other_addon_has_same_dir_files(self, tmp_path):
        project_dir = tmp_path / "myapp"
        project_dir.mkdir()
        pkg_dir = project_dir / "src" / "myapp" / "pkg"
        pkg_dir.mkdir(parents=True)

        # Addon A's files
        (pkg_dir / "__init__.py").write_text("")  # empty init
        (pkg_dir / "a.py").write_text("# addon A")
        # Addon B's file (same dir, different file)
        (pkg_dir / "b.py").write_text("# addon B")

        addon_a = AddonConfig(
            id="addon_a",
            description="",
            files=[
                FileContribution(dest="src/{{pkg_name}}/pkg/__init__.py", content=""),
                FileContribution(dest="src/{{pkg_name}}/pkg/a.py", content="# addon A"),
            ],
        )

        removed = _remove_files(project_dir, addon_a, "myapp")

        assert (project_dir / "src" / "myapp" / "pkg" / "__init__.py").exists()
        assert not (project_dir / "src" / "myapp" / "pkg" / "a.py").exists()
        assert (project_dir / "src" / "myapp" / "pkg" / "b.py").exists()
        assert "src/myapp/pkg/__init__.py" not in removed

    def test_empty_init_py_kept_when_other_addon_has_subdirectory(self, tmp_path):
        project_dir = tmp_path / "myapp"
        project_dir.mkdir()
        pkg_dir = project_dir / "src" / "myapp" / "pkg"
        pkg_dir.mkdir(parents=True)
        sub_dir = pkg_dir / "sub"
        sub_dir.mkdir()

        # Addon A's file (empty init in pkg/)
        (pkg_dir / "__init__.py").write_text("")
        # Addon B's files (subdirectory with its own init + module)
        (sub_dir / "__init__.py").write_text("")
        (sub_dir / "mod.py").write_text("# addon B")

        addon_a = AddonConfig(
            id="addon_a",
            description="",
            files=[
                FileContribution(dest="src/{{pkg_name}}/pkg/__init__.py", content=""),
            ],
        )

        removed = _remove_files(project_dir, addon_a, "myapp")

        assert (project_dir / "src" / "myapp" / "pkg" / "__init__.py").exists()
        assert "src/myapp/pkg/__init__.py" not in removed

    def test_empty_init_py_deleted_when_directory_truly_empty(self, tmp_path):
        project_dir = tmp_path / "myapp"
        project_dir.mkdir()
        pkg_dir = project_dir / "src" / "myapp" / "pkg"
        pkg_dir.mkdir(parents=True)

        (pkg_dir / "__init__.py").write_text("")
        (pkg_dir / "mod.py").write_text("# addon A")

        addon_a = AddonConfig(
            id="addon_a",
            description="",
            files=[
                FileContribution(dest="src/{{pkg_name}}/pkg/__init__.py", content=""),
                FileContribution(
                    dest="src/{{pkg_name}}/pkg/mod.py", content="# addon A"
                ),
            ],
        )

        removed = _remove_files(project_dir, addon_a, "myapp")

        assert not (project_dir / "src" / "myapp" / "pkg" / "__init__.py").exists()
        assert not (project_dir / "src" / "myapp" / "pkg" / "mod.py").exists()
        assert not (project_dir / "src" / "myapp" / "pkg").exists()
        assert "src/myapp/pkg/__init__.py" in removed

    def test_cannot_remove_unknown_addon(self):
        with suppress_stdin(), pytest.raises(ZenitError):
            remove_addon("nonexistent")

    def test_cannot_remove_from_non_zenit_project(self, tmp_path, monkeypatch):
        project_dir = tmp_path / "myapp"
        project_dir.mkdir()
        monkeypatch.chdir(project_dir)

        with suppress_stdin(), pytest.raises(ZenitError):
            remove_addon("docker", project_dir=project_dir)

    def test_remove_fuzzy_blocks_requires_confirmation(self, tmp_path, monkeypatch):
        """When injected code has been modified, the user must explicitly consent
        to fuzzy removal before it proceeds. Answering "n" aborts; answering "y"
        proceeds with fuzzy matching.
        """
        project_dir = _scaffold(tmp_path, "myapi", "fastapi", ["sentry"])
        settings = project_dir / "src" / "myapi" / "settings.py"
        original = settings.read_text()
        assert "sentry_dsn" in original

        # Modify injected code enough to break Stage A/B fingerprints.
        modified = original.replace("sentry_dsn", "sentry_dsn_val")
        settings.write_text(modified)

        # ── Answer "n" → abort, block stays ────────────────────────────────
        with (
            patch("sys.stdin.isatty", return_value=True),
            patch("builtins.input", return_value="n"),
            pytest.raises(typer.Exit) as exc,
        ):
            remove_addon("sentry", project_dir=project_dir)
        assert exc.value.exit_code == 0
        assert "sentry_dsn_val" in settings.read_text()

        # ── Answer "y" → fuzzy removal succeeds, block gone ────────────────
        with (
            patch("sys.stdin.isatty", return_value=True),
            patch("builtins.input", side_effect=["y", ""]),
        ):
            remove_addon("sentry", project_dir=project_dir)

        remaining = settings.read_text()
        assert "sentry_dsn_val" not in remaining
        assert "sentry_environment" not in remaining

    def test_remove_fuzzy_blocks_fails_with_yes_flag(self, tmp_path):
        """When --yes is passed and fuzzy blocks are detected, removal must
        error out telling the user to re-run interactively."""
        project_dir = _scaffold(tmp_path, "myapi", "fastapi", ["sentry"])
        settings = project_dir / "src" / "myapi" / "settings.py"
        original = settings.read_text()
        assert "sentry_dsn" in original

        modified = original.replace("sentry_dsn", "sentry_dsn_val")
        settings.write_text(modified)

        with pytest.raises(typer.Exit) as exc:
            remove_addon("sentry", project_dir=project_dir, yes=True)
        assert exc.value.exit_code == 1

        # Block must NOT have been removed
        assert "sentry_dsn_val" in settings.read_text()


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
        # _refresh_compose reconciles compose.yml with remaining addons
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

    def test_remove_interactive_multi(self, tmp_path, monkeypatch):
        """Multi-remove via interactive: select 2, verify both removed."""
        project_dir = _scaffold(
            tmp_path, "myapp", "blank", ["docker", "redis", "sentry"]
        )
        monkeypatch.chdir(project_dir)

        with (
            patch(
                "zenit.addons.remove.prompt_multi_addon",
                return_value=["redis", "sentry"],
            ),
            patch("builtins.input", return_value=""),
        ):
            from zenit.addons.remove import remove_addon_interactive

            remove_addon_interactive()

        lockfile = read_lockfile(project_dir)
        assert "redis" not in lockfile.addons
        assert "sentry" not in lockfile.addons
        assert "docker" in lockfile.addons

    def test_remove_interactive_keeps_deps_satisfied(self, tmp_path, monkeypatch):
        """Removing celery then redis keeps docker (which has no deps)."""
        project_dir = _scaffold(
            tmp_path, "myapp", "blank", ["docker", "redis", "celery"]
        )
        monkeypatch.chdir(project_dir)

        with (
            patch(
                "zenit.addons.remove.prompt_multi_addon",
                return_value=["celery", "redis"],
            ),
            patch("builtins.input", return_value=""),
        ):
            from zenit.addons.remove import remove_addon_interactive

            remove_addon_interactive()

        lockfile = read_lockfile(project_dir)
        assert "celery" not in lockfile.addons
        assert "redis" not in lockfile.addons
        assert "docker" in lockfile.addons

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

    def test_remove_docker_from_fastapi_succeeds(self, tmp_path, monkeypatch):
        """Docker is no longer required by fastapi — removing it should succeed."""
        project_dir = _scaffold(tmp_path, "myapi", "fastapi", ["docker", "sentry"])
        monkeypatch.chdir(project_dir)

        with suppress_stdin():
            remove_addon("docker", project_dir=project_dir)

        assert not (project_dir / "compose.yml").exists()
        assert not (project_dir / "Dockerfile").exists()


# ── Migrated-project tests ──────────────────────────────────────────────────────


def test_remove_on_copier_project_preserves_template_info(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression test: remove_addon must preserve copier template info."""
    from zenit.addons.add import add_addon

    # Scaffold a blank project (no addons installed)
    project_dir = _scaffold(tmp_path, "myapp", "blank", [])

    # Write the lockfile with copier metadata but NO addons
    write_lockfile(
        project_dir,
        "https://example.com/template",
        [],
        template_source="copier",
        template_uri="https://example.com/template",
    )

    monkeypatch.chdir(project_dir)

    # Add docker
    with suppress_stdin():
        add_addon("docker", project_dir=project_dir)

    lockfile = read_lockfile(project_dir)
    assert lockfile is not None
    assert lockfile.template_source == "copier"
    assert "docker" in lockfile.addons

    # Remove docker
    with suppress_stdin():
        remove_addon("docker", project_dir=project_dir)

    lockfile = read_lockfile(project_dir)
    assert lockfile is not None
    assert lockfile.template_source == "copier"
    assert lockfile.template_uri == "https://example.com/template"
    assert lockfile.addons == []


# ── Crash-safety / retry tests ─────────────────────────────────────────────────


class TestRemoveCrashSafety:
    """Tests that remove_addon is resilient to partial/crashed state."""

    def test_retry_after_missing_file(self, tmp_path):
        """Remove succeeds when a file is already gone (crash after _remove_files)."""
        project_dir = _scaffold(tmp_path, "myapp", "blank", ["sentry"])

        sentry_file = project_dir / "src" / "myapp" / "integrations" / "sentry.py"
        assert sentry_file.exists()
        sentry_file.unlink()

        with suppress_stdin():
            remove_addon("sentry", project_dir=project_dir)

        assert not sentry_file.exists()
        manifest = read_manifest(project_dir)
        assert not any(b.addon == "sentry" for b in manifest.python_blocks)

    def test_retry_after_missing_manifest_entries(self, tmp_path):
        """Remove succeeds when manifest python_blocks already cleaned (crash mid-write)."""
        project_dir = _scaffold(tmp_path, "myapp", "blank", ["sentry"])

        manifest = read_manifest(project_dir)
        manifest.python_blocks = [
            b for b in manifest.python_blocks if b.addon != "sentry"
        ]
        write_manifest(project_dir, manifest)

        with suppress_stdin():
            remove_addon("sentry", project_dir=project_dir)

        manifest_after = read_manifest(project_dir)
        assert not any(b.addon == "sentry" for b in manifest_after.python_blocks)
        assert not any(e.addon == "sentry" for e in manifest_after.env)
        assert not any(d.addon == "sentry" for d in manifest_after.dependencies)

    def test_retry_after_partial_env_removal(self, tmp_path):
        """Remove succeeds when an env file has already had entries removed."""
        project_dir = _scaffold(tmp_path, "myapp", "blank", ["redis"])

        env_path = project_dir / ".env"
        lines = env_path.read_text(encoding="utf-8").splitlines(keepends=True)
        env_path.write_text(
            "".join(line for line in lines if not line.startswith("REDIS_URL")),
            encoding="utf-8",
        )

        with suppress_stdin():
            remove_addon("redis", project_dir=project_dir)

        env_after = (project_dir / ".env").read_text()
        assert "REDIS_URL" not in env_after
        manifest = read_manifest(project_dir)
        assert not any(e.addon == "redis" for e in manifest.env)
