"""Tests for zenit.add — adding addons to existing projects.

Organised in two sections:
  - Pipeline unit tests: verify that add_addon correctly writes files,
    injects deps, adds just recipes, updates the lockfile, and applies
    injections, using a real scaffolded project as the starting point.
  - Existing tests: pyproject format preservation and interactive output.
"""

from __future__ import annotations

import os
import re
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from click.exceptions import Exit as ClickExit
from helpers import ZENIT_ROOT, write_test_manifest

from zenit.addons._registry import get_available_addons
from zenit.addons.add import add_addon, add_addon_interactive
from zenit.addons.remove import remove_addon
from zenit.cli.prompt._single import prompt_single_addon
from zenit.core._apply_loader import load_apply
from zenit.core.apply import apply_contributions
from zenit.core.collect import collect_all
from zenit.core.context import Context
from zenit.core.filesystem import RealFileSystem
from zenit.core.generate import generate_all
from zenit.core.git import init
from zenit.core.lockfile import read_lockfile, write_lockfile
from zenit.core.render import build_render_vars
from zenit.schema.models import OwnedEntry
from zenit.templates._load_config import load_template_config

# ── helpers ───────────────────────────────────────────────────────────────────


@contextmanager
def suppress_stdin():
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
        yield


def _scaffold(tmp_path: Path, name: str, template: str, addons: list[str]) -> Path:
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

    load_apply(ZENIT_ROOT / "templates" / "_common" / "apply.py")(ctx, fs)

    available = get_available_addons()
    template_config = load_template_config(ZENIT_ROOT, template)
    selected = [c for c in available if c.id in addons]
    render_vars = build_render_vars(
        name=name,
        pkg_name=pkg_name,
        template=template,
        addons=addons,
    )

    contributions = collect_all(template_config, selected)
    apply_contributions(
        ctx, fs, contributions, template_config.injection_points, render_vars
    )
    generate_all(ctx, fs, contributions)
    write_test_manifest(project_dir, addons, render_vars)
    init(project_dir)
    write_lockfile(project_dir, template, addons)
    return project_dir


# ── add_addon — migrated-project tests ─────────────────────────────────────────


def test_add_overwrite_warning_fires(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Addon file destinations overlapping with template_file_paths must warn."""
    project_dir = _scaffold(tmp_path, "myapp", "blank", [])
    write_lockfile(
        project_dir,
        "https://example.com/template",
        [],
        template_source="copier",
        template_uri="https://example.com/template",
        template_file_paths=["Dockerfile"],
    )

    with suppress_stdin():
        add_addon("docker", project_dir=project_dir)

    stderr = capsys.readouterr().err
    assert "Dockerfile" in stderr
    assert "override" in stderr


def test_full_add_on_migrated_lifecycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Add an addon on a Copier project adopts TEMPLATE entries, then remove
    correctly cleans up the adopted (ADDON) entries without touching other
    TEMPLATE content."""
    from zenit.core.manifest import read_manifest as _rd
    from zenit.core.manifest import write_manifest as _wr
    from zenit.schema.models import EntrySource

    project_dir = _scaffold(tmp_path, "myapp", "blank", [])

    # Ensure docker is "installed" so compose contributions are allowed
    with suppress_stdin():
        add_addon("docker", project_dir=project_dir)

    # Write a TEMPLATE compose_service entry (simulating a Copier template that wrote compose entries)
    manifest = _rd(project_dir)
    manifest.compose_services.append(
        OwnedEntry(name="redis", source=EntrySource.TEMPLATE, addon="")
    )
    _wr(project_dir, manifest)

    # Write lockfile with copier metadata and docker installed
    write_lockfile(
        project_dir,
        "https://example.com/template",
        ["docker"],
        template_source="copier",
        template_uri="https://example.com/template",
    )

    monkeypatch.chdir(project_dir)

    # ── Step 1: Add redis ──────────────────────────────────────────────────
    with suppress_stdin():
        add_addon("redis")

    manifest = _rd(project_dir)
    redis_entry = next(
        (e for e in manifest.compose_services if e.name == "redis"), None
    )
    assert redis_entry is not None
    assert redis_entry.source == EntrySource.ADDON
    assert redis_entry.addon == "docker"

    # ── Step 2: Remove redis ───────────────────────────────────────────────
    with suppress_stdin():
        from zenit.addons.remove import remove_addon

        remove_addon("redis", project_dir=project_dir)

    manifest = _rd(project_dir)
    redis_entry = next(
        (e for e in manifest.compose_services if e.name == "redis"), None
    )
    # Docker owns compose — removing redis does NOT remove compose entries
    assert redis_entry is not None
    assert redis_entry.addon == "docker"


# ── add_addon — lockfile ──────────────────────────────────────────────────────


def test_add_updates_lockfile(tmp_path, monkeypatch):
    project_dir = _scaffold(tmp_path, "myapp", "blank", [])
    monkeypatch.chdir(project_dir)
    with suppress_stdin():
        add_addon("docker")
    lockfile = read_lockfile(project_dir)
    assert "docker" in lockfile.addons


def test_add_preserves_existing_addons_in_lockfile(tmp_path, monkeypatch):
    project_dir = _scaffold(tmp_path, "myapp", "blank", ["docker"])
    monkeypatch.chdir(project_dir)
    with suppress_stdin():
        add_addon("sentry")
    lockfile = read_lockfile(project_dir)
    assert "docker" in lockfile.addons
    assert "sentry" in lockfile.addons


def test_add_lockfile_template_unchanged(tmp_path, monkeypatch):
    project_dir = _scaffold(tmp_path, "myapp", "blank", [])
    monkeypatch.chdir(project_dir)
    with suppress_stdin():
        add_addon("docker")
    lockfile = read_lockfile(project_dir)
    assert lockfile.template == "blank"


def test_add_on_migrated_project_preserves_template(tmp_path, monkeypatch):
    project_dir = _scaffold(tmp_path, "myapp", "blank", [])
    write_lockfile(
        project_dir,
        "https://github.com/example/copier-template",
        [],
        template_source="copier",
        template_uri="https://github.com/example/copier-template",
    )
    monkeypatch.chdir(project_dir)
    with suppress_stdin():
        add_addon("docker")
    lockfile = read_lockfile(project_dir)
    assert lockfile.template == "https://github.com/example/copier-template"
    assert lockfile.template_source == "copier"
    assert "docker" in lockfile.addons


# ── add_addon — files ─────────────────────────────────────────────────────────


def test_add_docker_creates_dockerfile(tmp_path, monkeypatch):
    project_dir = _scaffold(tmp_path, "myapp", "blank", [])
    monkeypatch.chdir(project_dir)
    with suppress_stdin():
        add_addon("docker")
    assert (project_dir / "Dockerfile").exists()


def test_add_docker_creates_compose_yml(tmp_path, monkeypatch):
    project_dir = _scaffold(tmp_path, "myapp", "blank", [])
    monkeypatch.chdir(project_dir)
    with suppress_stdin():
        add_addon("docker")
    assert (project_dir / "compose.yml").exists()


def test_add_docker_creates_dockerignore(tmp_path, monkeypatch):
    project_dir = _scaffold(tmp_path, "myapp", "blank", [])
    monkeypatch.chdir(project_dir)
    with suppress_stdin():
        add_addon("docker")
    assert (project_dir / ".dockerignore").exists()


def test_add_redis_creates_integration_file(tmp_path, monkeypatch):
    project_dir = _scaffold(tmp_path, "myapp", "blank", [])
    monkeypatch.chdir(project_dir)
    with suppress_stdin():
        add_addon("redis")
    assert (project_dir / "src" / "myapp" / "integrations" / "redis.py").exists()


def test_add_sentry_creates_integration_file(tmp_path, monkeypatch):
    project_dir = _scaffold(tmp_path, "myapp", "blank", [])
    monkeypatch.chdir(project_dir)
    with suppress_stdin():
        add_addon("sentry")
    assert (project_dir / "src" / "myapp" / "integrations" / "sentry.py").exists()


def test_add_github_actions_creates_workflow(tmp_path, monkeypatch):
    project_dir = _scaffold(tmp_path, "myapp", "blank", [])
    monkeypatch.chdir(project_dir)
    with suppress_stdin():
        add_addon("github-actions")
    assert (project_dir / ".github" / "workflows" / "ci.yml").exists()


def test_add_celery_creates_task_files(tmp_path, monkeypatch):
    project_dir = _scaffold(tmp_path, "myapp", "blank", ["docker", "redis"])
    monkeypatch.chdir(project_dir)
    with suppress_stdin():
        add_addon("celery")
    assert (project_dir / "src" / "myapp" / "tasks" / "celery_app.py").exists()
    assert (project_dir / "src" / "myapp" / "tasks" / "example_tasks.py").exists()


# ── add_addon — deps ──────────────────────────────────────────────────────────


def test_add_docker_adds_just_recipes(tmp_path, monkeypatch):
    project_dir = _scaffold(tmp_path, "myapp", "blank", [])
    monkeypatch.chdir(project_dir)
    with suppress_stdin():
        add_addon("docker")
    justfile = (project_dir / "justfile").read_text()
    assert "docker-up:" in justfile
    assert "docker-down:" in justfile


def test_add_redis_adds_just_recipes(tmp_path, monkeypatch):
    project_dir = _scaffold(tmp_path, "myapp", "blank", ["docker"])
    monkeypatch.chdir(project_dir)
    with suppress_stdin():
        add_addon("redis")
    justfile = (project_dir / "justfile").read_text()
    assert "redis-up:" in justfile
    assert "redis-down:" in justfile
    assert "redis-cli:" in justfile


def test_add_sentry_adds_just_recipes(tmp_path, monkeypatch):
    project_dir = _scaffold(tmp_path, "myapp", "blank", [])
    monkeypatch.chdir(project_dir)
    with suppress_stdin():
        add_addon("sentry")
    justfile = (project_dir / "justfile").read_text()
    assert "sentry-check:" in justfile
    assert "sentry-test:" in justfile


def test_add_celery_adds_just_recipes(tmp_path, monkeypatch):
    project_dir = _scaffold(tmp_path, "myapp", "blank", ["docker", "redis"])
    monkeypatch.chdir(project_dir)
    with suppress_stdin():
        add_addon("celery")
    justfile = (project_dir / "justfile").read_text()
    assert "celery-up:" in justfile
    assert "celery-down:" in justfile
    assert "celery-flower:" in justfile
    assert "celery-logs:" in justfile


def test_add_does_not_duplicate_recipes(tmp_path, monkeypatch):
    project_dir = _scaffold(tmp_path, "myapp", "blank", [])
    monkeypatch.chdir(project_dir)
    with suppress_stdin():
        add_addon("docker")
    justfile = (project_dir / "justfile").read_text()
    assert justfile.count("docker-up:") == 1
    assert justfile.count("docker-down:") == 1


# ── add_addon — env vars ──────────────────────────────────────────────────────


def test_add_redis_adds_env_var(tmp_path, monkeypatch):
    project_dir = _scaffold(tmp_path, "myapp", "blank", [])
    monkeypatch.chdir(project_dir)
    with suppress_stdin():
        add_addon("redis")
    env = (project_dir / ".env").read_text()
    assert "REDIS_URL=" in env


def test_add_sentry_adds_env_vars(tmp_path, monkeypatch):
    project_dir = _scaffold(tmp_path, "myapp", "blank", [])
    monkeypatch.chdir(project_dir)
    with suppress_stdin():
        add_addon("sentry")
    env = (project_dir / ".env").read_text()
    assert "SENTRY_DSN=" in env
    assert "SENTRY_ENVIRONMENT=" in env


def test_add_env_var_also_in_env_example(tmp_path, monkeypatch):
    project_dir = _scaffold(tmp_path, "myapi", "fastapi", ["docker"])
    monkeypatch.chdir(project_dir)
    with suppress_stdin():
        add_addon("redis")
    env_example = (project_dir / ".env.example").read_text()
    assert "REDIS_URL=" in env_example


# ── add_addon — injections ────────────────────────────────────────────────────


def test_add_sentry_blank_injects_init_sentry_into_main(tmp_path, monkeypatch):
    project_dir = _scaffold(tmp_path, "myapp", "blank", [])
    monkeypatch.chdir(project_dir)
    with suppress_stdin():
        add_addon("sentry")
    main = (project_dir / "src" / "myapp" / "main.py").read_text()
    assert "init_sentry" in main


def test_add_sentry_fastapi_injects_into_lifecycle(tmp_path, monkeypatch):
    project_dir = _scaffold(tmp_path, "myapi", "fastapi", ["docker"])
    monkeypatch.chdir(project_dir)
    with suppress_stdin():
        add_addon("sentry")
    lifecycle = (project_dir / "src" / "myapi" / "lifecycle.py").read_text()
    assert "init_sentry" in lifecycle


def test_add_redis_fastapi_injects_redis_url_into_settings(tmp_path, monkeypatch):
    project_dir = _scaffold(tmp_path, "myapi", "fastapi", ["docker"])
    monkeypatch.chdir(project_dir)
    with suppress_stdin():
        add_addon("redis")
    settings = (project_dir / "src" / "myapi" / "settings.py").read_text()
    assert "redis_url" in settings


# ── add_addon — compose services ─────────────────────────────────────────────


def test_add_redis_merges_compose_service(tmp_path, monkeypatch):
    project_dir = _scaffold(tmp_path, "myapp", "blank", ["docker"])
    monkeypatch.chdir(project_dir)
    with suppress_stdin():
        add_addon("redis")
    data = yaml.safe_load((project_dir / "compose.yml").read_text())
    assert "redis" in data["services"]


def test_add_celery_merges_compose_services(tmp_path, monkeypatch):
    project_dir = _scaffold(tmp_path, "myapp", "blank", ["docker", "redis"])
    monkeypatch.chdir(project_dir)
    with suppress_stdin():
        add_addon("celery")
    data = yaml.safe_load((project_dir / "compose.yml").read_text())
    assert "celery-worker" in data["services"]
    assert "celery-beat" in data["services"]


# ── add_addon — error cases ───────────────────────────────────────────────────


def test_add_fails_when_addon_already_installed(tmp_path, monkeypatch):
    project_dir = _scaffold(tmp_path, "myapp", "blank", ["docker"])
    monkeypatch.chdir(project_dir)
    with pytest.raises(ClickExit), suppress_stdin():
        add_addon("docker")


def test_add_fails_when_dependency_missing(tmp_path, monkeypatch):
    project_dir = _scaffold(tmp_path, "myapp", "blank", [])
    monkeypatch.chdir(project_dir)
    with pytest.raises(ClickExit), suppress_stdin():
        add_addon("celery")


def test_add_fails_when_no_lockfile(tmp_path, monkeypatch):
    project_dir = tmp_path / "notazenit"
    project_dir.mkdir()
    monkeypatch.chdir(project_dir)
    with pytest.raises(ClickExit), suppress_stdin():
        add_addon("docker")


def test_add_fails_for_unknown_addon(tmp_path, monkeypatch):
    project_dir = _scaffold(tmp_path, "myapp", "blank", [])
    monkeypatch.chdir(project_dir)
    with pytest.raises(ClickExit), suppress_stdin():
        add_addon("nonexistent-addon")


def test_add_fails_template_incompatible_addon(tmp_path, monkeypatch):
    project_dir = _scaffold(tmp_path, "myapp", "blank", [])
    monkeypatch.chdir(project_dir)
    with pytest.raises(ClickExit), suppress_stdin():
        add_addon("auth-manual")


# ── pyproject.toml multiline format ───────────────────────────────────────────


class TestPyprojectFormatPreservation:
    """After a remove+add cycle, deps must remain one-per-line."""

    def _dep_lines(self, project_dir: Path) -> list[str]:
        text = (project_dir / "pyproject.toml").read_text()
        marker = "dependencies = ["
        idx = text.index(marker)
        m = re.search(r"^\]", text[idx:], re.MULTILINE)
        assert m is not None
        end = idx + m.start()
        inside = text[idx:end]
        return [
            line.strip() for line in inside.splitlines() if line.strip().startswith('"')
        ]

    def test_remove_leaves_deps_multiline(self, tmp_path, monkeypatch):
        project_dir = _scaffold(
            tmp_path, "myapp", "blank", ["docker", "redis", "sentry"]
        )
        monkeypatch.chdir(project_dir)
        with suppress_stdin():
            remove_addon("redis", project_dir=project_dir)
        dep_lines = self._dep_lines(project_dir)
        assert len(dep_lines) >= 1
        for line in dep_lines:
            assert line.count('"') == 2, f"Multiple deps on one line: {line!r}"

    def test_remove_then_add_deps_still_multiline(self, tmp_path, monkeypatch):
        project_dir = _scaffold(
            tmp_path, "myapp", "blank", ["docker", "redis", "sentry"]
        )
        monkeypatch.chdir(project_dir)
        with suppress_stdin():
            remove_addon("redis", project_dir=project_dir)
        with suppress_stdin():
            add_addon("redis")
        dep_lines = self._dep_lines(project_dir)
        assert any("redis" in line for line in dep_lines)
        for line in dep_lines:
            assert line.count('"') == 2, f"Multiple deps collapsed: {line!r}"

    def test_readded_dep_is_present_and_on_its_own_line(self, tmp_path, monkeypatch):
        project_dir = _scaffold(
            tmp_path, "myapp", "blank", ["docker", "redis", "sentry"]
        )
        monkeypatch.chdir(project_dir)
        with suppress_stdin():
            remove_addon("redis", project_dir=project_dir)
        with suppress_stdin():
            add_addon("redis")
        lines = (project_dir / "pyproject.toml").read_text().splitlines()
        redis_lines = [line.strip() for line in lines if '"redis>=5"' in line]
        assert len(redis_lines) == 1

    def test_dev_deps_also_stay_multiline_after_remove_add(self, tmp_path, monkeypatch):
        project_dir = _scaffold(tmp_path, "myapp", "blank", ["docker", "redis"])
        monkeypatch.chdir(project_dir)
        with suppress_stdin():
            remove_addon("redis", project_dir=project_dir)
        with suppress_stdin():
            add_addon("redis")
        text = (project_dir / "pyproject.toml").read_text()
        dev_block_start = text.index("[dependency-groups]")
        dev_block = text[dev_block_start : text.index("]", dev_block_start)]
        dev_lines = [
            line.strip()
            for line in dev_block.splitlines()
            if line.strip().startswith('"')
        ]
        for line in dev_lines:
            assert line.count('"') == 2, f"Multiple dev deps on one line: {line!r}"

    def test_full_fastapi_remove_add_cycle(self, tmp_path, monkeypatch):
        project_dir = _scaffold(
            tmp_path,
            "myapi",
            "fastapi",
            ["docker", "redis", "celery", "sentry", "github-actions"],
        )
        monkeypatch.chdir(project_dir)
        with suppress_stdin():
            remove_addon("celery", project_dir=project_dir)
        with suppress_stdin():
            add_addon("celery")
        dep_lines = self._dep_lines(project_dir)
        assert any("celery" in line for line in dep_lines)
        for line in dep_lines:
            assert line.count('"') == 2, f"Deps collapsed to one line: {line!r}"


# ── "Already installed" message deduplication ────────────────────────────────


class TestAlreadyInstalledMessage:
    def test_prompt_single_addon_does_not_print_already_installed(self, capsys):
        items = [
            ("docker", "Docker description", []),
            ("redis", "Redis description", []),
        ]
        with (
            patch("zenit.cli.prompt._keys.tty_available", return_value=False),
            patch("builtins.input", return_value=""),
        ):
            prompt_single_addon(items)
        out = capsys.readouterr().out
        assert "Already installed" not in out

    def test_add_interactive_prints_already_installed_once(
        self, tmp_path, monkeypatch, capsys
    ):
        project_dir = _scaffold(tmp_path, "myapp", "blank", ["docker"])
        monkeypatch.chdir(project_dir)
        with (
            patch("zenit.cli.prompt._keys.tty_available", return_value=False),
            patch("builtins.input", return_value=""),
        ):
            add_addon_interactive()
        out = capsys.readouterr().out
        assert out.count("Already installed") == 1


# ── Multi-addon interactive ──────────────────────────────────────────────────


class TestAddInteractiveMulti:
    """Tests for add_addon_interactive with multi-select support."""

    def test_interactive_select_two_addons(self, tmp_path, monkeypatch):
        project_dir = _scaffold(tmp_path, "myapp", "blank", ["docker"])
        monkeypatch.chdir(project_dir)
        with (
            patch(
                "zenit.addons.add.prompt_multi_addon", return_value=["redis", "sentry"]
            ),
            patch("builtins.input", return_value=""),
        ):
            add_addon_interactive()
        lockfile = read_lockfile(project_dir)
        assert "redis" in lockfile.addons
        assert "sentry" in lockfile.addons
        assert "docker" in lockfile.addons

    def test_interactive_select_one_addon(self, tmp_path, monkeypatch):
        project_dir = _scaffold(tmp_path, "myapp", "blank", ["docker"])
        monkeypatch.chdir(project_dir)
        with (
            patch("zenit.addons.add.prompt_multi_addon", return_value=["redis"]),
            patch("builtins.input", return_value=""),
        ):
            add_addon_interactive()
        lockfile = read_lockfile(project_dir)
        assert "redis" in lockfile.addons
        assert "docker" in lockfile.addons

    def test_interactive_select_none(self, tmp_path, monkeypatch, capsys):
        project_dir = _scaffold(tmp_path, "myapp", "blank", ["docker"])
        monkeypatch.chdir(project_dir)
        with (
            patch("zenit.addons.add.prompt_multi_addon", return_value=[]),
        ):
            add_addon_interactive()
        lockfile = read_lockfile(project_dir)
        assert lockfile.addons == ["docker"]
