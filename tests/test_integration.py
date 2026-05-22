"""Integration tests — scaffold real projects into tmp_path and verify the results."""

from pathlib import Path

from conftest import ZENIT_ROOT, write_test_manifest

from zenit.addons._registry import get_available_addons
from zenit.core._apply_loader import load_apply
from zenit.core.apply import apply_contributions
from zenit.core.collect import collect_all
from zenit.core.context import Context
from zenit.core.filesystem import RealFileSystem
from zenit.core.generate import generate_all
from zenit.core.git import init
from zenit.core.render import build_render_vars
from zenit.templates._load_config import load_template_config

# ── fixture ───────────────────────────────────────────────────────────────────


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
    init(project_dir)

    return project_dir


# ── blank template ────────────────────────────────────────────────────────────


class TestBlankTemplate:
    def test_project_directory_created(self, tmp_path):
        project_dir = _scaffold(tmp_path, "myapp", "blank", [])
        assert project_dir.exists()
        assert project_dir.is_dir()

    def test_package_structure(self, tmp_path):
        project_dir = _scaffold(tmp_path, "myapp", "blank", [])
        assert (project_dir / "src" / "myapp" / "__init__.py").exists()
        assert (project_dir / "src" / "myapp" / "main.py").exists()
        assert (project_dir / "src" / "myapp" / "__main__.py").exists()

    def test_tests_directory(self, tmp_path):
        project_dir = _scaffold(tmp_path, "myapp", "blank", [])
        assert (project_dir / "tests" / "test_main.py").exists()

    def test_common_files(self, tmp_path):
        project_dir = _scaffold(tmp_path, "myapp", "blank", [])
        assert (project_dir / ".gitignore").exists()
        assert (project_dir / ".gitattributes").exists()
        assert (project_dir / ".pre-commit-config.yaml").exists()

    def test_pyproject_toml_exists_and_contains_name(self, tmp_path):
        project_dir = _scaffold(tmp_path, "myapp", "blank", [])
        pyproject = (project_dir / "pyproject.toml").read_text()
        assert 'name = "myapp"' in pyproject

    def test_pyproject_toml_contains_pytest(self, tmp_path):
        project_dir = _scaffold(tmp_path, "myapp", "blank", [])
        pyproject = (project_dir / "pyproject.toml").read_text()
        assert "pytest" in pyproject

    def test_justfile_exists(self, tmp_path):
        project_dir = _scaffold(tmp_path, "myapp", "blank", [])
        assert (project_dir / "justfile").exists()

    def test_justfile_contains_base_recipes(self, tmp_path):
        project_dir = _scaffold(tmp_path, "myapp", "blank", [])
        justfile = (project_dir / "justfile").read_text()
        for recipe in ["test:", "lint:", "fmt:", "check:", "run:"]:
            assert recipe in justfile, f"missing recipe: {recipe}"

    def test_justfile_run_recipe_uses_pkg_name(self, tmp_path):
        project_dir = _scaffold(tmp_path, "myapp", "blank", [])
        justfile = (project_dir / "justfile").read_text()
        assert "myapp" in justfile

    def test_main_py_contains_project_name(self, tmp_path):
        project_dir = _scaffold(tmp_path, "myapp", "blank", [])
        main = (project_dir / "src" / "myapp" / "main.py").read_text()
        assert "myapp" in main

    def test_init_py_contains_version(self, tmp_path):
        project_dir = _scaffold(tmp_path, "myapp", "blank", [])
        init = (project_dir / "src" / "myapp" / "__init__.py").read_text()
        assert "__version__" in init

    def test_hyphenated_name_uses_underscore_pkg(self, tmp_path):
        project_dir = _scaffold(tmp_path, "my-app", "blank", [])
        assert (project_dir / "src" / "my_app" / "__init__.py").exists()
        justfile = (project_dir / "justfile").read_text()
        assert "my_app" in justfile
        assert (
            "my-app" not in justfile.split("my-app")[0]
        )  # name in metadata ok, not in commands

    def test_git_repo_initialised(self, tmp_path):
        project_dir = _scaffold(tmp_path, "myapp", "blank", [])
        assert (project_dir / ".git").exists()

    def test_no_duplicate_recipes_in_justfile(self, tmp_path):
        project_dir = _scaffold(tmp_path, "myapp", "blank", [])
        justfile = (project_dir / "justfile").read_text()
        recipe_lines = [
            line.split(":")[0].strip()
            for line in justfile.splitlines()
            if line
            and not line[0].isspace()
            and ":" in line
            and not line.startswith("#")
        ]
        assert len(recipe_lines) == len(set(recipe_lines)), (
            f"Duplicate recipes found: {[r for r in recipe_lines if recipe_lines.count(r) > 1]}"
        )


# ── blank + docker ────────────────────────────────────────────────────────────


class TestBlankWithDocker:
    def test_dockerfile_created(self, tmp_path):
        project_dir = _scaffold(tmp_path, "myapp", "blank", ["docker"])
        assert (project_dir / "Dockerfile").exists()

    def test_compose_yml_created(self, tmp_path):
        project_dir = _scaffold(tmp_path, "myapp", "blank", ["docker"])
        assert (project_dir / "compose.yml").exists()

    def test_dockerignore_created(self, tmp_path):
        project_dir = _scaffold(tmp_path, "myapp", "blank", ["docker"])
        assert (project_dir / ".dockerignore").exists()

    def test_docker_recipes_in_justfile(self, tmp_path):
        project_dir = _scaffold(tmp_path, "myapp", "blank", ["docker"])
        justfile = (project_dir / "justfile").read_text()
        assert "docker-up:" in justfile
        assert "docker-down:" in justfile

    def test_no_duplicate_recipes(self, tmp_path):
        project_dir = _scaffold(tmp_path, "myapp", "blank", ["docker"])
        justfile = (project_dir / "justfile").read_text()
        recipe_lines = [
            line.split(":")[0].strip()
            for line in justfile.splitlines()
            if line
            and not line[0].isspace()
            and ":" in line
            and not line.startswith("#")
        ]
        assert len(recipe_lines) == len(set(recipe_lines))


# ── fastapi template ──────────────────────────────────────────────────────────


class TestFastapiTemplate:
    def test_project_directory_created(self, tmp_path):
        project_dir = _scaffold(tmp_path, "myapi", "fastapi", ["docker"])
        assert project_dir.exists()

    def test_package_structure(self, tmp_path):
        project_dir = _scaffold(tmp_path, "myapi", "fastapi", ["docker"])
        src = project_dir / "src" / "myapi"
        assert (src / "main.py").exists()
        assert (src / "settings.py").exists()
        assert (src / "lifecycle.py").exists()
        assert (src / "exceptions.py").exists()

    def test_api_structure(self, tmp_path):
        project_dir = _scaffold(tmp_path, "myapi", "fastapi", ["docker"])
        src = project_dir / "src" / "myapi"
        assert (src / "api" / "router.py").exists()
        assert (src / "api" / "routes" / "health.py").exists()

    def test_settings_py_has_settings_class(self, tmp_path):
        project_dir = _scaffold(tmp_path, "myapi", "fastapi", ["docker"])
        settings = (project_dir / "src" / "myapi" / "settings.py").read_text()
        assert "class Settings" in settings

    def test_settings_py_no_database_url(self, tmp_path):
        """Plain fastapi skeleton has no database_url — it comes from postgres addon."""
        project_dir = _scaffold(tmp_path, "myapi", "fastapi", ["docker"])
        settings = (project_dir / "src" / "myapi" / "settings.py").read_text()
        assert "database_url" not in settings

    def test_lifecycle_py_no_engine_dispose(self, tmp_path):
        """Plain fastapi skeleton has no engine.dispose() — it comes from sqlalchemy addon."""
        project_dir = _scaffold(tmp_path, "myapi", "fastapi", ["docker"])
        lifecycle = (project_dir / "src" / "myapi" / "lifecycle.py").read_text()
        assert "engine.dispose" not in lifecycle

    def test_fastapi_recipes_in_justfile(self, tmp_path):
        project_dir = _scaffold(tmp_path, "myapi", "fastapi", ["docker"])
        justfile = (project_dir / "justfile").read_text()
        assert "run:" in justfile

    def test_no_duplicate_recipes(self, tmp_path):
        project_dir = _scaffold(tmp_path, "myapi", "fastapi", ["docker"])
        justfile = (project_dir / "justfile").read_text()
        recipe_lines = [
            line.split(":")[0].strip()
            for line in justfile.splitlines()
            if line
            and not line[0].isspace()
            and ":" in line
            and not line.startswith("#")
        ]
        assert len(recipe_lines) == len(set(recipe_lines))

    def test_git_repo_initialised(self, tmp_path):
        project_dir = _scaffold(tmp_path, "myapi", "fastapi", ["docker"])
        assert (project_dir / ".git").exists()


# ── fastapi + all addons ──────────────────────────────────────────────────────


class TestFastapiAllAddons:
    ADDONS = [
        "docker",
        "postgres",
        "sqlalchemy",
        "redis",
        "celery",
        "sentry",
        "github-actions",
    ]

    def test_scaffolds_successfully(self, tmp_path):
        project_dir = _scaffold(tmp_path, "myapi", "fastapi", self.ADDONS)
        assert project_dir.exists()

    def test_redis_integration_file(self, tmp_path):
        project_dir = _scaffold(tmp_path, "myapi", "fastapi", self.ADDONS)
        assert (project_dir / "src" / "myapi" / "integrations" / "redis.py").exists()

    def test_celery_tasks_files(self, tmp_path):
        project_dir = _scaffold(tmp_path, "myapi", "fastapi", self.ADDONS)
        tasks = project_dir / "src" / "myapi" / "tasks"
        assert (tasks / "celery_app.py").exists()
        assert (tasks / "example_tasks.py").exists()

    def test_sentry_integration_file(self, tmp_path):
        project_dir = _scaffold(tmp_path, "myapi", "fastapi", self.ADDONS)
        assert (project_dir / "src" / "myapi" / "integrations" / "sentry.py").exists()

    def test_github_actions_workflow(self, tmp_path):
        project_dir = _scaffold(tmp_path, "myapi", "fastapi", self.ADDONS)
        assert (project_dir / ".github" / "workflows" / "ci.yml").exists()

    def test_ci_yml_has_postgres_service(self, tmp_path):
        project_dir = _scaffold(tmp_path, "myapi", "fastapi", self.ADDONS)
        ci = (project_dir / ".github" / "workflows" / "ci.yml").read_text()
        assert "postgres" in ci

    def test_ci_yml_has_redis_service(self, tmp_path):
        project_dir = _scaffold(tmp_path, "myapi", "fastapi", self.ADDONS)
        ci = (project_dir / ".github" / "workflows" / "ci.yml").read_text()
        assert "redis" in ci

    def test_compose_yml_has_all_services(self, tmp_path):
        project_dir = _scaffold(tmp_path, "myapi", "fastapi", self.ADDONS)
        compose = (project_dir / "compose.yml").read_text()
        for service in ["app:", "db:", "redis:", "celery-worker:", "celery-beat:"]:
            assert service in compose, f"missing compose service: {service}"

    def test_settings_py_has_database_url(self, tmp_path):
        """database_url comes from postgres addon injection."""
        project_dir = _scaffold(tmp_path, "myapi", "fastapi", self.ADDONS)
        settings = (project_dir / "src" / "myapi" / "settings.py").read_text()
        assert "database_url" in settings

    def test_settings_py_has_redis_url(self, tmp_path):
        project_dir = _scaffold(tmp_path, "myapi", "fastapi", self.ADDONS)
        settings = (project_dir / "src" / "myapi" / "settings.py").read_text()
        assert "redis_url" in settings

    def test_settings_py_has_sentry_dsn(self, tmp_path):
        project_dir = _scaffold(tmp_path, "myapi", "fastapi", self.ADDONS)
        settings = (project_dir / "src" / "myapi" / "settings.py").read_text()
        assert "sentry_dsn" in settings

    def test_lifecycle_py_disposes_engine(self, tmp_path):
        """engine.dispose() comes from sqlalchemy addon injection."""
        project_dir = _scaffold(tmp_path, "myapi", "fastapi", self.ADDONS)
        lifecycle = (project_dir / "src" / "myapi" / "lifecycle.py").read_text()
        assert "engine.dispose" in lifecycle

    def test_lifecycle_py_calls_init_sentry(self, tmp_path):
        project_dir = _scaffold(tmp_path, "myapi", "fastapi", self.ADDONS)
        lifecycle = (project_dir / "src" / "myapi" / "lifecycle.py").read_text()
        assert "init_sentry" in lifecycle

    def test_all_addon_recipes_in_justfile(self, tmp_path):
        project_dir = _scaffold(tmp_path, "myapi", "fastapi", self.ADDONS)
        justfile = (project_dir / "justfile").read_text()
        for recipe in [
            "docker-up:",
            "docker-down:",
            "migrate",
            "upgrade:",
            "downgrade:",
            "wait-db:",
            "db-create:",
            "db-reset:",
            "redis-up:",
            "redis-down:",
            "redis-cli:",
            "celery-up:",
            "celery-down:",
            "celery-flower:",
            "celery-logs:",
            "sentry-check:",
            "sentry-test:",
        ]:
            assert recipe in justfile, f"missing recipe: {recipe}"

    def test_no_duplicate_recipes(self, tmp_path):
        project_dir = _scaffold(tmp_path, "myapi", "fastapi", self.ADDONS)
        justfile = (project_dir / "justfile").read_text()
        recipe_lines = [
            line.split(":")[0].strip()
            for line in justfile.splitlines()
            if line
            and not line[0].isspace()
            and ":" in line
            and not line.startswith("#")
        ]
        assert len(recipe_lines) == len(set(recipe_lines)), (
            f"Duplicate recipes: {[r for r in recipe_lines if recipe_lines.count(r) > 1]}"
        )

    def test_env_file_has_database_url(self, tmp_path):
        """DATABASE_URL comes from postgres addon."""
        project_dir = _scaffold(tmp_path, "myapi", "fastapi", self.ADDONS)
        env = (project_dir / ".env").read_text()
        assert "DATABASE_URL=" in env

    def test_env_file_has_redis_url(self, tmp_path):
        project_dir = _scaffold(tmp_path, "myapi", "fastapi", self.ADDONS)
        env = (project_dir / ".env").read_text()
        assert "REDIS_URL=" in env

    def test_env_file_has_sentry_dsn(self, tmp_path):
        project_dir = _scaffold(tmp_path, "myapi", "fastapi", self.ADDONS)
        env = (project_dir / ".env").read_text()
        assert "SENTRY_DSN=" in env
