"""Tests for addon can_apply hooks.

All can_apply functions derive pkg_name from project_dir.name.
Tests must therefore create a project directory with a predictable name
(e.g. `tmp_path / "myapp"`) and build the file tree inside it.
"""

from __future__ import annotations

from pathlib import Path

from zenit.addons._registry import get_addon
from zenit.core.lockfile import ZenitLockfile

# ── helpers ───────────────────────────────────────────────────────────────────


def _lockfile(**kw) -> ZenitLockfile:
    return ZenitLockfile(**kw)


def _project_dir(tmp_path: Path, name: str = "myapp") -> Path:
    d = tmp_path / name
    d.mkdir()
    return d


def _get_can_apply(addon_id: str):
    """Return the can_apply function for an addon, or None if it doesn't have one."""
    cfg = get_addon(addon_id)
    hooks = cfg._module
    return hooks.can_apply if hooks is not None else None
    return None


# ── docker ────────────────────────────────────────────────────────────────────


class TestDockerCanApply:
    def test_docker_passes_clean_project(self, tmp_path):
        project_dir = _project_dir(tmp_path, "myapp")
        (project_dir / "src").mkdir()
        (project_dir / "pyproject.toml").write_text("")
        result = _get_can_apply("docker")(project_dir, _lockfile())
        assert result is None

    def test_docker_fails_no_src_directory(self, tmp_path):
        project_dir = _project_dir(tmp_path, "myapp")
        (project_dir / "pyproject.toml").write_text("")
        result = _get_can_apply("docker")(project_dir, _lockfile())
        assert result is not None
        assert "src/" in result

    def test_docker_fails_no_pyproject(self, tmp_path):
        project_dir = _project_dir(tmp_path, "myapp")
        (project_dir / "src").mkdir()
        result = _get_can_apply("docker")(project_dir, _lockfile())
        assert result is not None
        assert "pyproject.toml" in result

    def test_docker_fails_dockerfile_already_exists(self, tmp_path):
        project_dir = _project_dir(tmp_path, "myapp")
        (project_dir / "src").mkdir()
        (project_dir / "pyproject.toml").write_text("")
        (project_dir / "Dockerfile").write_text("# existing")
        result = _get_can_apply("docker")(project_dir, _lockfile())
        assert result is not None
        assert "Dockerfile" in result

    def test_docker_fails_compose_yml_already_exists(self, tmp_path):
        project_dir = _project_dir(tmp_path, "myapp")
        (project_dir / "src").mkdir()
        (project_dir / "pyproject.toml").write_text("")
        (project_dir / "compose.yml").write_text("")
        result = _get_can_apply("docker")(project_dir, _lockfile())
        assert result is not None
        assert "compose.yml" in result

    def test_docker_fails_docker_compose_yml_already_exists(self, tmp_path):
        project_dir = _project_dir(tmp_path, "myapp")
        (project_dir / "src").mkdir()
        (project_dir / "pyproject.toml").write_text("")
        (project_dir / "docker-compose.yml").write_text("")
        result = _get_can_apply("docker")(project_dir, _lockfile())
        assert result is not None
        assert "docker-compose.yml" in result


# ── redis ─────────────────────────────────────────────────────────────────────


class TestRedisCanApply:
    def test_redis_passes_clean_project(self, tmp_path):
        project_dir = _project_dir(tmp_path, "myapp")
        (project_dir / "src").mkdir()
        result = _get_can_apply("redis")(project_dir, _lockfile())
        assert result is None

    def test_redis_fails_no_src_directory(self, tmp_path):
        project_dir = _project_dir(tmp_path, "myapp")
        result = _get_can_apply("redis")(project_dir, _lockfile())
        assert result is not None
        assert "src/" in result

    def test_redis_fails_redis_py_already_exists(self, tmp_path):
        project_dir = _project_dir(tmp_path, "myapp")
        src = project_dir / "src" / "myapp"
        integrations = src / "integrations"
        integrations.mkdir(parents=True)
        (integrations / "redis.py").write_text("# existing\n")
        result = _get_can_apply("redis")(project_dir, _lockfile())
        assert result is not None
        assert "redis.py" in result

    def test_redis_fails_existing_file_references_redis(self, tmp_path):
        project_dir = _project_dir(tmp_path, "myapp")
        src = project_dir / "src" / "myapp"
        integrations = src / "integrations"
        integrations.mkdir(parents=True)
        (integrations / "another.py").write_text("import redis\n")
        result = _get_can_apply("redis")(project_dir, _lockfile())
        assert result is not None
        assert "redis" in result.lower()

    def test_redis_fails_redis_url_in_env(self, tmp_path):
        project_dir = _project_dir(tmp_path, "myapp")
        src = project_dir / "src" / "myapp"
        src.mkdir(parents=True)
        (project_dir / ".env").write_text("REDIS_URL=redis://localhost\n")
        result = _get_can_apply("redis")(project_dir, _lockfile())
        assert result is not None
        assert "REDIS_URL" in result

    def test_redis_fails_redis_url_in_env_example(self, tmp_path):
        project_dir = _project_dir(tmp_path, "myapp")
        src = project_dir / "src" / "myapp"
        src.mkdir(parents=True)
        (project_dir / ".env.example").write_text("REDIS_URL=\n")
        result = _get_can_apply("redis")(project_dir, _lockfile())
        assert result is not None
        assert "REDIS_URL" in result

    def test_redis_passes_when_redis_import_in_non_integration_file(self, tmp_path):
        """General source scan was removed for perf — redis only checks targeted paths."""
        project_dir = _project_dir(tmp_path, "myapp")
        src = project_dir / "src" / "myapp"
        src.mkdir(parents=True)
        (src / "main.py").write_text("import redis\n")
        result = _get_can_apply("redis")(project_dir, _lockfile())
        assert result is None


# ── sentry ────────────────────────────────────────────────────────────────────


class TestSentryCanApply:
    def test_sentry_passes_clean_blank_project(self, tmp_path):
        project_dir = _project_dir(tmp_path, "myapp")
        src = project_dir / "src" / "myapp"
        src.mkdir(parents=True)
        (src / "main.py").write_text("def main():\n    pass\n")
        result = _get_can_apply("sentry")(project_dir, _lockfile(template="blank"))
        assert result is None

    def test_sentry_passes_clean_fastapi_project(self, tmp_path):
        project_dir = _project_dir(tmp_path, "myapi")
        src = project_dir / "src" / "myapi"
        src.mkdir(parents=True)
        (src / "lifecycle.py").write_text("async def lifespan(app):\n    yield\n")
        result = _get_can_apply("sentry")(project_dir, _lockfile(template="fastapi"))
        assert result is None

    def test_sentry_fails_no_src_directory(self, tmp_path):
        project_dir = _project_dir(tmp_path, "myapp")
        result = _get_can_apply("sentry")(project_dir, _lockfile(template="blank"))
        assert result is not None
        assert "src/" in result

    def test_sentry_fails_sentry_py_already_exists(self, tmp_path):
        project_dir = _project_dir(tmp_path, "myapp")
        src = project_dir / "src" / "myapp"
        src.mkdir(parents=True)
        # Target file must exist so check reaches sentry.py
        (src / "main.py").write_text("def main(): pass\n")
        integrations = src / "integrations"
        integrations.mkdir()
        (integrations / "sentry.py").write_text("# existing\n")
        result = _get_can_apply("sentry")(project_dir, _lockfile(template="blank"))
        assert result is not None
        assert "sentry.py" in result

    def test_sentry_fails_lifecycle_missing_for_fastapi(self, tmp_path):
        project_dir = _project_dir(tmp_path, "myapi")
        (project_dir / "src").mkdir()
        result = _get_can_apply("sentry")(project_dir, _lockfile(template="fastapi"))
        assert result is not None
        assert "lifecycle.py" in result

    def test_sentry_fails_lifecycle_already_has_sentry_sdk(self, tmp_path):
        project_dir = _project_dir(tmp_path, "myapi")
        src = project_dir / "src" / "myapi"
        src.mkdir(parents=True)
        (src / "lifecycle.py").write_text("import sentry_sdk\nsentry_sdk.init()\n")
        result = _get_can_apply("sentry")(project_dir, _lockfile(template="fastapi"))
        assert result is not None
        assert "sentry_sdk" in result

    def test_sentry_fails_main_missing_for_blank(self, tmp_path):
        project_dir = _project_dir(tmp_path, "myapp")
        (project_dir / "src").mkdir()
        result = _get_can_apply("sentry")(project_dir, _lockfile(template="blank"))
        assert result is not None
        assert "main.py" in result

    def test_sentry_fails_main_already_has_sentry_sdk(self, tmp_path):
        project_dir = _project_dir(tmp_path, "myapp")
        src = project_dir / "src" / "myapp"
        src.mkdir(parents=True)
        (src / "main.py").write_text("import sentry_sdk\nsentry_sdk.init()\n")
        result = _get_can_apply("sentry")(project_dir, _lockfile(template="blank"))
        assert result is not None
        assert "sentry_sdk" in result

    def test_sentry_fails_sentry_dsn_in_env(self, tmp_path):
        project_dir = _project_dir(tmp_path, "myapp")
        src = project_dir / "src" / "myapp"
        src.mkdir(parents=True)
        (src / "main.py").write_text("def main(): pass\n")
        (project_dir / ".env").write_text("SENTRY_DSN=https://example.sentry.io/123\n")
        result = _get_can_apply("sentry")(project_dir, _lockfile(template="blank"))
        assert result is not None
        assert "SENTRY_DSN" in result

    def test_sentry_fails_sentry_dsn_in_env_example(self, tmp_path):
        project_dir = _project_dir(tmp_path, "myapp")
        src = project_dir / "src" / "myapp"
        src.mkdir(parents=True)
        (src / "main.py").write_text("def main(): pass\n")
        (project_dir / ".env.example").write_text("SENTRY_DSN=\n")
        result = _get_can_apply("sentry")(project_dir, _lockfile(template="blank"))
        assert result is not None
        assert "SENTRY_DSN" in result


# ── celery ────────────────────────────────────────────────────────────────────


class TestCeleryCanApply:
    def test_celery_passes_clean_project(self, tmp_path):
        project_dir = _project_dir(tmp_path, "myapp")
        (project_dir / "src").mkdir()
        result = _get_can_apply("celery")(project_dir, _lockfile())
        assert result is None

    def test_celery_fails_no_src_directory(self, tmp_path):
        project_dir = _project_dir(tmp_path, "myapp")
        result = _get_can_apply("celery")(project_dir, _lockfile())
        assert result is not None
        assert "src/" in result

    def test_celery_fails_tasks_dir_has_python_files(self, tmp_path):
        project_dir = _project_dir(tmp_path, "myapp")
        src = project_dir / "src" / "myapp"
        tasks = src / "tasks"
        tasks.mkdir(parents=True)
        (tasks / "celery_app.py").write_text("# existing\n")
        result = _get_can_apply("celery")(project_dir, _lockfile())
        assert result is not None
        assert "tasks" in result

    def test_celery_fails_existing_celery_import_in_targeted_file(self, tmp_path):
        project_dir = _project_dir(tmp_path, "myapp")
        src = project_dir / "src" / "myapp"
        src.mkdir(parents=True)
        (src / "celery.py").write_text(
            "from celery import Celery\napp = Celery('tasks')\n"
        )
        result = _get_can_apply("celery")(project_dir, _lockfile())
        assert result is not None
        assert "celery" in result.lower()

    def test_celery_passes_when_celery_import_in_non_targeted_file(self, tmp_path):
        """General source scan was removed for perf — celery only checks targeted paths."""
        project_dir = _project_dir(tmp_path, "myapp")
        src = project_dir / "src" / "myapp"
        src.mkdir(parents=True)
        (src / "some_random.py").write_text("from celery import Celery\n")
        result = _get_can_apply("celery")(project_dir, _lockfile())
        assert result is None

    def test_celery_passes_empty_tasks_directory(self, tmp_path):
        project_dir = _project_dir(tmp_path, "myapp")
        src = project_dir / "src" / "myapp"
        tasks = src / "tasks"
        tasks.mkdir(parents=True)
        result = _get_can_apply("celery")(project_dir, _lockfile())
        assert result is None


# ── github-actions ────────────────────────────────────────────────────────────


class TestGithubActionsCanApply:
    def test_github_actions_passes_clean_project(self, tmp_path):
        project_dir = _project_dir(tmp_path, "myapp")
        result = _get_can_apply("github-actions")(project_dir, _lockfile())
        assert result is None

    def test_github_actions_fails_ci_yml_already_exists(self, tmp_path):
        project_dir = _project_dir(tmp_path, "myapp")
        workflows = project_dir / ".github" / "workflows"
        workflows.mkdir(parents=True)
        (workflows / "ci.yml").write_text("name: CI\n")
        result = _get_can_apply("github-actions")(project_dir, _lockfile())
        assert result is not None
        assert "ci.yml" in result

    def test_github_actions_passes_workflows_dir_missing(self, tmp_path):
        project_dir = _project_dir(tmp_path, "myapp")
        result = _get_can_apply("github-actions")(project_dir, _lockfile())
        assert result is None

    def test_github_actions_passes_workflows_dir_empty(self, tmp_path):
        project_dir = _project_dir(tmp_path, "myapp")
        (project_dir / ".github" / "workflows").mkdir(parents=True)
        result = _get_can_apply("github-actions")(project_dir, _lockfile())
        assert result is None


# ── auth-manual ───────────────────────────────────────────────────────────────


class TestAuthManualCanApply:
    def test_auth_manual_fails_non_fastapi_template(self, tmp_path):
        project_dir = _project_dir(tmp_path, "myapp")
        result = _get_can_apply("auth-manual")(project_dir, _lockfile(template="blank"))
        assert result is not None
        assert "fastapi" in result.lower()

    def test_auth_manual_passes_clean_fastapi_project(self, tmp_path):
        project_dir = _project_dir(tmp_path, "myapi")
        src = project_dir / "src" / "myapi"
        src.mkdir(parents=True)
        result = _get_can_apply("auth-manual")(
            project_dir, _lockfile(template="fastapi")
        )
        assert result is None

    def test_auth_manual_fails_security_py_already_exists(self, tmp_path):
        project_dir = _project_dir(tmp_path, "myapi")
        src = project_dir / "src" / "myapi"
        core = src / "core"
        core.mkdir(parents=True)
        (core / "security.py").write_text("# existing\n")
        result = _get_can_apply("auth-manual")(
            project_dir, _lockfile(template="fastapi")
        )
        assert result is not None
        assert "security.py" in result

    def test_auth_manual_fails_auth_route_already_exists(self, tmp_path):
        project_dir = _project_dir(tmp_path, "myapi")
        src = project_dir / "src" / "myapi"
        routes = src / "api" / "routes"
        routes.mkdir(parents=True)
        (routes / "auth.py").write_text("# existing\n")
        result = _get_can_apply("auth-manual")(
            project_dir, _lockfile(template="fastapi")
        )
        assert result is not None
        assert "auth.py" in result

    def test_auth_manual_fails_secret_key_in_env(self, tmp_path):
        project_dir = _project_dir(tmp_path, "myapi")
        src = project_dir / "src" / "myapi"
        src.mkdir(parents=True)
        (project_dir / ".env").write_text("SECRET_KEY=abc\n")
        result = _get_can_apply("auth-manual")(
            project_dir, _lockfile(template="fastapi")
        )
        assert result is not None
        assert "SECRET_KEY" in result

    def test_auth_manual_fails_secret_key_in_env_example(self, tmp_path):
        project_dir = _project_dir(tmp_path, "myapi")
        src = project_dir / "src" / "myapi"
        src.mkdir(parents=True)
        (project_dir / ".env.example").write_text("SECRET_KEY=\n")
        result = _get_can_apply("auth-manual")(
            project_dir, _lockfile(template="fastapi")
        )
        assert result is not None
        assert "SECRET_KEY" in result
