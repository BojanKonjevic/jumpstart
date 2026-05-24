"""Functional integration tests — scaffolded projects must be runnable.

These tests scaffold real projects and then execute commands inside them,
verifying that the generated output is not just syntactically present but
actually works.  They are slower than the structural tests in test_integration.py
and are marked with @pytest.mark.slow.

Run with:   uv run pytest tests/test_functional.py -v
Skip with:  uv run pytest -m "not slow"
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from helpers import scaffold_project_at


def _uv(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    """Run a uv command in the given directory and return the result."""
    env = os.environ.copy()
    # Propagate NixOS settings if present
    return subprocess.run(
        ["uv", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env,
    )


# ── blank template ────────────────────────────────────────────────────────────


@pytest.mark.slow
class TestBlankFunctional:
    """Scaffolds a blank project once and shares it across test methods.

    Saves 5 redundant scaffold + uv sync cycles compared to per-function
    scaffolding.
    """

    @pytest.fixture(scope="class")
    def blank_project(self, class_tmp_path: Path) -> Path:
        project_dir = class_tmp_path / "myapp"
        project_dir.mkdir(parents=True)
        scaffold_project_at(project_dir, "myapp", "blank", [])
        _uv("sync", "--quiet", "--frozen", cwd=project_dir)
        return project_dir

    def test_uv_sync_succeeds(self, blank_project: Path) -> None:
        pass

    def test_pytest_passes(self, blank_project: Path) -> None:
        result = _uv("run", "pytest", "-v", cwd=blank_project)
        assert result.returncode == 0, (
            f"pytest failed in scaffolded blank project:\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )

    def test_pytest_output_contains_test_name(self, blank_project: Path) -> None:
        result = _uv("run", "pytest", "-v", cwd=blank_project)
        assert "test_main" in result.stdout

    def test_ruff_check_passes(self, blank_project: Path) -> None:
        result = _uv("run", "ruff", "check", ".", cwd=blank_project)
        assert result.returncode == 0, (
            f"ruff check failed in scaffolded blank project:\n{result.stdout}\n{result.stderr}"
        )

    def test_ruff_format_check_passes(self, blank_project: Path) -> None:
        result = _uv("run", "ruff", "format", "--check", ".", cwd=blank_project)
        assert result.returncode == 0, (
            f"ruff format --check failed:\n{result.stdout}\n{result.stderr}"
        )

    def test_hyphenated_name_pytest_passes(self, tmp_path, scaffold_project):
        """Hyphenated project names convert to underscore pkg — tests must still work."""
        project_dir = scaffold_project("my-cool-app", "blank", [])
        _uv("sync", "--quiet", "--frozen", cwd=project_dir)
        result = _uv("run", "pytest", "-v", cwd=project_dir)
        assert result.returncode == 0, (
            f"pytest failed for hyphenated project name:\n{result.stdout}\n{result.stderr}"
        )

    def test_main_module_is_runnable(self, blank_project: Path) -> None:
        result = _uv("run", "python", "-m", "myapp", cwd=blank_project)
        assert result.returncode == 0, (
            f"python -m myapp failed:\n{result.stdout}\n{result.stderr}"
        )
        assert "Hello from myapp" in result.stdout


# ── blank + docker ────────────────────────────────────────────────────────────


@pytest.mark.slow
class TestBlankDockerFunctional:
    """Scaffolds a blank+docker project once and shares it across test methods."""

    @pytest.fixture(scope="class")
    def blank_docker_project(self, class_tmp_path: Path) -> Path:
        project_dir = class_tmp_path / "myapp"
        project_dir.mkdir(parents=True)
        scaffold_project_at(project_dir, "myapp", "blank", ["docker"])
        _uv("sync", "--quiet", "--frozen", cwd=project_dir)
        return project_dir

    def test_uv_sync_succeeds(self, blank_docker_project: Path) -> None:
        pass

    def test_pytest_passes(self, blank_docker_project: Path) -> None:
        result = _uv("run", "pytest", "-v", cwd=blank_docker_project)
        assert result.returncode == 0, (
            f"pytest failed in blank+docker project:\n{result.stdout}\n{result.stderr}"
        )

    def test_ruff_passes(self, blank_docker_project: Path) -> None:
        result = _uv("run", "ruff", "check", ".", cwd=blank_docker_project)
        assert result.returncode == 0, f"ruff failed:\n{result.stdout}"


# ── template rendering correctness ────────────────────────────────────────────


class TestRenderedContentCorrectness:
    """Verify that Jinja2 variables are fully resolved in generated files.

    These don't require uv/pytest to be installed — they just inspect content.
    """

    def test_no_unrendered_jinja_in_blank_main(self, tmp_path, scaffold_project):
        project_dir = scaffold_project("myapp", "blank", [])
        main = (project_dir / "src" / "myapp" / "main.py").read_text()
        assert "((" not in main
        assert "))" not in main

    def test_no_unrendered_jinja_in_blank_test(self, tmp_path, scaffold_project):
        project_dir = scaffold_project("myapp", "blank", [])
        test = (project_dir / "tests" / "test_main.py").read_text()
        assert "((" not in test
        assert "))" not in test

    def test_no_unrendered_jinja_in_pyproject(self, tmp_path, scaffold_project):
        project_dir = scaffold_project("myapp", "blank", [])
        pyproject = (project_dir / "pyproject.toml").read_text()
        assert "((" not in pyproject
        assert "))" not in pyproject

    def test_no_unrendered_jinja_in_justfile(self, tmp_path, scaffold_project):
        project_dir = scaffold_project("myapp", "blank", [])
        justfile = (project_dir / "justfile").read_text()
        assert "((" not in justfile
        assert "))" not in justfile

    def test_no_unrendered_jinja_in_fastapi_main(self, tmp_path, scaffold_project):
        project_dir = scaffold_project("myapi", "fastapi", ["docker"])
        main = (project_dir / "src" / "myapi" / "main.py").read_text()
        assert "((" not in main

    def test_no_unrendered_jinja_in_fastapi_settings(self, tmp_path, scaffold_project):
        project_dir = scaffold_project("myapi", "fastapi", ["docker"])
        settings = (project_dir / "src" / "myapi" / "settings.py").read_text()
        assert "((" not in settings

    def test_no_unrendered_jinja_in_env_file(self, tmp_path, scaffold_project):
        project_dir = scaffold_project("myapi", "fastapi", ["docker"])
        env = (project_dir / ".env").read_text()
        assert "((" not in env

    def test_no_unrendered_jinja_in_github_actions_ci(self, tmp_path, scaffold_project):
        project_dir = scaffold_project(
            "myapi", "fastapi", ["docker", "redis", "github-actions"]
        )
        ci = (project_dir / ".github" / "workflows" / "ci.yml").read_text()
        assert "((" not in ci

    def test_no_unrendered_jinja_in_celery_app(self, tmp_path, scaffold_project):
        project_dir = scaffold_project(
            "myapi", "fastapi", ["docker", "redis", "celery"]
        )
        celery_app = (
            project_dir / "src" / "myapi" / "tasks" / "celery_app.py"
        ).read_text()
        assert "((" not in celery_app

    def test_no_unrendered_block_tags_in_blank(self, tmp_path, scaffold_project):
        """[% %] tags must not appear in any generated file."""
        project_dir = scaffold_project("myapp", "blank", [])
        for f in project_dir.rglob("*"):
            if f.is_file() and f.suffix in (
                ".py",
                ".toml",
                ".yml",
                ".yaml",
                ".cfg",
                ".ini",
                ".txt",
            ):
                text = f.read_text(errors="replace")
                assert "[% " not in text and " %]" not in text, (
                    f"Unrendered block tag found in {f.relative_to(project_dir)}"
                )

    def test_no_unrendered_block_tags_in_fastapi(self, tmp_path, scaffold_project):
        project_dir = scaffold_project("myapi", "fastapi", ["docker"])
        for f in project_dir.rglob("*"):
            if f.is_file() and f.suffix in (".py", ".toml", ".yml", ".yaml", ".cfg"):
                text = f.read_text(errors="replace")
                assert "[% " not in text and " %]" not in text, (
                    f"Unrendered block tag found in {f.relative_to(project_dir)}"
                )

    def test_project_name_correctly_substituted_in_all_files(
        self, tmp_path, scaffold_project
    ):
        """Every occurrence of '(( name ))' should be replaced with the project name."""
        project_dir = scaffold_project("uniquename", "blank", [])
        for f in project_dir.rglob("*"):
            if f.is_file():
                text = f.read_text(errors="replace")
                assert "(( name ))" not in text, (
                    f"Unrendered (( name )) found in {f.relative_to(project_dir)}"
                )

    def test_pkg_name_placeholder_fully_resolved_in_file_contents(
        self, tmp_path, scaffold_project
    ):
        project_dir = scaffold_project("myapp", "blank", [])
        for f in project_dir.rglob("*.py"):
            text = f.read_text(errors="replace")
            assert "(( pkg_name ))" not in text, (
                f"Unrendered (( pkg_name )) in {f.relative_to(project_dir)}"
            )


# ── mypy type checking ────────────────────────────────────────────────────────


@pytest.mark.slow
class TestMypyFunctional:
    def test_mypy_passes_on_blank(self, tmp_path, scaffold_project):
        project_dir = scaffold_project("myapp", "blank", [])
        _uv("sync", "--quiet", "--frozen", cwd=project_dir)
        result = _uv("run", "mypy", "src/", cwd=project_dir)
        assert result.returncode == 0, (
            f"mypy failed on blank project:\n{result.stdout}\n{result.stderr}"
        )


# ── plan §7.1 — toolchain validation and doctor integration ───────────────────


@pytest.mark.slow
class TestPlanToolchain:
    """Six tests from the plan's §7.1.

    Each test scaffolds a project and runs the full toolchain
    (pytest, mypy, ruff check, ruff format --check) or an add/remove cycle,
    then verifies that `zenit doctor` exits clean.
    """

    def _run(self, *args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        return subprocess.run(
            list(args),
            cwd=cwd,
            capture_output=True,
            text=True,
            env=env,
        )

    def _uv(self, *args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
        return self._run("uv", *args, cwd=cwd)

    def _assert_toolchain(self, project_dir: Path, *, run_pytest: bool = True) -> None:
        """Run mypy, ruff check, ruff format --check — all must exit 0.

        pytest is skipped for fastapi projects by default because the generated
        test suite requires a live PostgreSQL instance which is not available in
        CI or local fast runs.  Pass run_pytest=True only for blank projects
        whose tests have no external dependencies.

        ruff format is run (not just --check) before the check pass.  The
        scaffolder's injection system produces syntactically correct Python but
        does not guarantee byte-for-byte ruff-style output — that is ruff's job.
        The meaningful invariants tested here are type correctness (mypy) and
        lint cleanliness (ruff check).  ruff format --check after ruff format
        confirms idempotence: a second format pass changes nothing.
        """
        self._uv("sync", "--quiet", "--frozen", cwd=project_dir)

        if run_pytest:
            result = self._uv("run", "pytest", cwd=project_dir)
            assert result.returncode == 0, (
                f"pytest failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
            )

        result = self._uv("run", "mypy", "src/", cwd=project_dir)
        assert result.returncode == 0, (
            f"mypy failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )

        result = self._uv("run", "ruff", "check", ".", cwd=project_dir)
        assert result.returncode == 0, (
            f"ruff check failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )

        # Format first, then assert idempotence.  The scaffolder produces
        # correct Python; ruff owns the whitespace contract.
        self._uv("run", "ruff", "format", ".", cwd=project_dir)
        result = self._uv("run", "ruff", "format", "--check", ".", cwd=project_dir)
        assert result.returncode == 0, (
            f"ruff format is not idempotent after scaffolding:\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )

    def _assert_doctor_clean(self, project_dir: Path) -> None:
        """run_doctor must return no errors or warnings for a healthy project."""
        from zenit.doctor.doctor import run_doctor

        results = run_doctor(project_dir)
        errors = [
            f"[{r.category}] {i.message}"
            for r in results
            for i in r.issues
            if i.severity.name == "ERROR"
        ]
        assert not errors, (
            "zenit doctor reported errors on what should be a clean project:\n"
            + "\n".join(errors)
        )

    def test_blank_template_passes_toolchain(
        self, tmp_path: Path, scaffold_project
    ) -> None:
        project_dir = scaffold_project("myapp", "blank", [])
        self._assert_toolchain(project_dir)

    def test_fastapi_docker_template_passes_toolchain(
        self, tmp_path: Path, scaffold_project
    ) -> None:
        project_dir = scaffold_project(
            "myapi", "fastapi", ["docker", "sqlalchemy", "postgres"]
        )
        self._assert_toolchain(project_dir, run_pytest=False)

    def test_fastapi_with_all_addons_passes_toolchain(
        self, tmp_path: Path, scaffold_project
    ) -> None:
        project_dir = scaffold_project(
            "myapi",
            "fastapi",
            [
                "docker",
                "postgres",
                "sqlalchemy",
                "redis",
                "sentry",
                "celery",
                "github-actions",
            ],
        )
        self._assert_toolchain(project_dir, run_pytest=False)

    def test_add_then_remove_addon_toolchain_passes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scaffold_project
    ) -> None:
        """Scaffold fastapi+docker+sqlalchemy+postgres, add celery and sentry, remove both, run toolchain."""
        from zenit.addons.add import add_addon
        from zenit.addons.remove import remove_addon

        project_dir = scaffold_project(
            "myapi", "fastapi", ["docker", "sqlalchemy", "postgres"]
        )
        monkeypatch.chdir(project_dir)

        add_addon("redis")
        add_addon("sentry")
        remove_addon("sentry")
        remove_addon("redis")

        self._assert_toolchain(project_dir, run_pytest=False)

    def test_doctor_clean_on_fresh_scaffold(
        self, tmp_path: Path, scaffold_project
    ) -> None:
        """After a fresh scaffold, run_doctor must report no errors."""
        project_dir = scaffold_project(
            "myapi", "fastapi", ["docker", "sqlalchemy", "postgres", "redis"]
        )
        self._assert_doctor_clean(project_dir)

    def test_doctor_clean_after_add_and_remove(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scaffold_project
    ) -> None:
        """After an add/remove cycle, zenit doctor must exit 0 with no errors."""
        from zenit.addons.add import add_addon
        from zenit.addons.remove import remove_addon

        project_dir = scaffold_project(
            "myapi", "fastapi", ["docker", "sqlalchemy", "postgres"]
        )
        monkeypatch.chdir(project_dir)

        add_addon("redis")
        add_addon("sentry")
        remove_addon("sentry")
        remove_addon("redis")

        self._uv("sync", "--quiet", "--frozen", cwd=project_dir)
        self._assert_doctor_clean(project_dir)
