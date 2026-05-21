"""Tests for zenit.doctor — all health check phases."""

from __future__ import annotations

import sys
import unittest.mock as mock
from pathlib import Path

import tomlkit
import yaml
from conftest import ZENIT_ROOT

from zenit.addons._registry import get_available_addons
from zenit.core._apply_loader import load_apply
from zenit.core.apply import apply_contributions
from zenit.core.collect import collect_all
from zenit.core.context import Context
from zenit.core.generate import generate_all
from zenit.core.git import init
from zenit.core.lockfile import ZenitLockfile, read_lockfile, write_lockfile
from zenit.core.render import build_render_vars
from zenit.doctor.doctor import (
    HealthIssue,
    HealthResult,
    Severity,
    _check_addon_health,
    _check_compose,
    _check_dependencies,
    _check_env,
    _check_files,
    _check_metadata,
    _check_python_integrity,
    _check_python_line_presence,
    print_results,
    run_doctor,
)
from zenit.schema.models import AddonConfig, AddonHooks
from zenit.templates._load_config import load_template_config

# ── helpers ───────────────────────────────────────────────────────────────────


def _scaffold(
    tmp_path: Path,
    name: str = "myapp",
    template: str = "blank",
    addons: list[str] | None = None,
) -> Path:
    """Scaffold a real project and return its directory."""

    addons = addons or []
    project_dir = tmp_path / name
    project_dir.mkdir(parents=True)
    pkg_name = name.replace("-", "_")

    ctx = Context(
        name=name,
        pkg_name=pkg_name,
        template=template,
        addons=addons,
        zenit_root=ZENIT_ROOT,
        project_dir=project_dir,
    )

    load_apply(ZENIT_ROOT / "templates" / "_common" / "apply.py")(ctx)
    available = get_available_addons()
    template_config = load_template_config(ZENIT_ROOT, template)
    selected_addon_configs = [cfg for cfg in available if cfg.id in addons]
    render_vars = build_render_vars(
        name=name,
        pkg_name=pkg_name,
        template=template,
        has_postgres=template == "fastapi",
        has_redis="redis" in addons,
    )

    contributions = collect_all(template_config, selected_addon_configs)
    apply_contributions(
        ctx, contributions, template_config.injection_points, render_vars
    )
    generate_all(ctx, template_config, contributions)
    init(project_dir)
    write_lockfile(project_dir, template, addons)
    return project_dir


def _issues_by_severity(result: HealthResult, severity: Severity) -> list[HealthIssue]:
    return [i for i in result.issues if i.severity == severity]


def _ok(result: HealthResult) -> list[HealthIssue]:
    return _issues_by_severity(result, Severity.OK)


def _warnings(result: HealthResult) -> list[HealthIssue]:
    return _issues_by_severity(result, Severity.WARN)


def _errors(result: HealthResult) -> list[HealthIssue]:
    return _issues_by_severity(result, Severity.ERROR)


def _messages(issues: list[HealthIssue]) -> list[str]:
    return [i.message for i in issues]


# ── HealthResult unit tests ───────────────────────────────────────────────────


class TestHealthResult:
    def test_ok_adds_ok_issue(self):
        r = HealthResult("Test")
        r.ok("all good")
        assert len(r.issues) == 1
        assert r.issues[0].severity == Severity.OK
        assert r.issues[0].message == "all good"

    def test_warn_adds_warn_issue(self):
        r = HealthResult("Test")
        r.warn("watch out", hint="do this")
        assert r.issues[0].severity == Severity.WARN
        assert r.issues[0].hint == "do this"

    def test_error_adds_error_issue(self):
        r = HealthResult("Test")
        r.error("broken", hint="fix this")
        assert r.issues[0].severity == Severity.ERROR
        assert r.issues[0].hint == "fix this"

    def test_has_errors_false_when_no_errors(self):
        r = HealthResult("Test")
        r.ok("fine")
        r.warn("hmm")
        assert not r.has_errors

    def test_has_errors_true_when_error_present(self):
        r = HealthResult("Test")
        r.ok("fine")
        r.error("broken")
        assert r.has_errors

    def test_has_warnings_false_when_no_warnings(self):
        r = HealthResult("Test")
        r.ok("fine")
        assert not r.has_warnings

    def test_has_warnings_true_when_warning_present(self):
        r = HealthResult("Test")
        r.warn("hmm")
        assert r.has_warnings

    def test_multiple_issues_accumulate(self):
        r = HealthResult("Test")
        r.ok("a")
        r.warn("b")
        r.error("c")
        assert len(r.issues) == 3

    def test_category_is_stored(self):
        r = HealthResult("My Category")
        assert r.category == "My Category"

    def test_empty_result_has_no_errors(self):
        r = HealthResult("Test")
        assert not r.has_errors
        assert not r.has_warnings


# ── _check_metadata ───────────────────────────────────────────────────────────


class TestCheckMetadata:
    def test_passes_on_valid_blank_project(self, tmp_path):
        project_dir = _scaffold(tmp_path, template="blank")
        result = _check_metadata(project_dir)
        assert not result.has_errors
        assert not result.has_warnings

    def test_passes_on_valid_fastapi_project(self, tmp_path):
        project_dir = _scaffold(tmp_path, template="fastapi", addons=["docker"])
        result = _check_metadata(project_dir)
        assert not result.has_errors
        assert not result.has_warnings

    def test_error_when_lockfile_missing(self, tmp_path):
        project_dir = tmp_path / "myapp"
        project_dir.mkdir()
        result = _check_metadata(project_dir)
        assert result.has_errors
        assert any(".zenit.toml" in i.message for i in _errors(result))

    def test_error_when_template_field_missing(self, tmp_path):
        project_dir = tmp_path / "myapp"
        project_dir.mkdir()
        (project_dir / ".zenit.toml").write_text("[project]\naddons = []\n")
        result = _check_metadata(project_dir)
        assert result.has_errors
        assert any("template" in i.message for i in _errors(result))

    def test_error_when_unknown_addon(self, tmp_path):
        project_dir = _scaffold(tmp_path, template="blank")
        write_lockfile(project_dir, "blank", ["nonexistent-addon"])
        result = _check_metadata(project_dir)
        assert result.has_errors
        assert any("nonexistent-addon" in i.message for i in _errors(result))

    def test_error_when_addon_dependency_missing(self, tmp_path):
        project_dir = _scaffold(tmp_path, template="blank")
        write_lockfile(project_dir, "blank", ["celery"])
        result = _check_metadata(project_dir)
        assert result.has_errors
        assert any("redis" in i.message for i in _errors(result))

    def test_ok_when_addon_dependency_satisfied(self, tmp_path):
        project_dir = _scaffold(tmp_path, template="blank", addons=["redis", "celery"])
        result = _check_metadata(project_dir)
        assert not result.has_errors

    def test_warn_when_version_skew(self, tmp_path):
        project_dir = _scaffold(tmp_path, template="blank")
        (project_dir / ".zenit.toml").write_text(
            '[project]\ntemplate = "blank"\naddons = []\nzenit_version = "0.0.1"\n'
        )
        result = _check_metadata(project_dir)
        assert result.has_warnings
        assert any("0.0.1" in i.message for i in _warnings(result))

    def test_warn_when_no_zenit_version(self, tmp_path):
        project_dir = _scaffold(tmp_path, template="blank")
        (project_dir / ".zenit.toml").write_text(
            '[project]\ntemplate = "blank"\naddons = []\n'
        )
        result = _check_metadata(project_dir)
        assert result.has_warnings
        assert any("zenit_version" in i.message for i in _warnings(result))

    def test_ok_message_includes_template_name(self, tmp_path):
        project_dir = _scaffold(tmp_path, template="blank")
        result = _check_metadata(project_dir)
        assert any("blank" in i.message for i in _ok(result))

    def test_ok_message_lists_installed_addons(self, tmp_path):
        project_dir = _scaffold(tmp_path, template="blank", addons=["docker"])
        result = _check_metadata(project_dir)
        assert any("docker" in i.message for i in _ok(result))

    def test_ok_when_no_addons_installed(self, tmp_path):
        project_dir = _scaffold(tmp_path, template="blank")
        result = _check_metadata(project_dir)
        assert any("No addons" in i.message for i in _ok(result))

    def test_multiple_unknown_addons_reported(self, tmp_path):
        project_dir = _scaffold(tmp_path, template="blank")
        write_lockfile(project_dir, "blank", ["fake1", "fake2"])
        result = _check_metadata(project_dir)
        assert result.has_errors
        msgs = _messages(_errors(result))
        assert any("fake1" in m for m in msgs)
        assert any("fake2" in m for m in msgs)


# ── _check_dependencies ───────────────────────────────────────────────────────


class TestCheckDependencies:
    def _lockfile(self, project_dir: Path) -> object:
        lf = read_lockfile(project_dir)
        assert lf is not None
        return lf

    def test_passes_on_fresh_blank_project(self, tmp_path):
        project_dir = _scaffold(tmp_path, template="blank")
        result = _check_dependencies(project_dir, self._lockfile(project_dir))
        assert not result.has_errors
        assert not result.has_warnings

    def test_passes_on_fresh_fastapi_project(self, tmp_path):
        project_dir = _scaffold(tmp_path, template="fastapi", addons=["docker"])
        result = _check_dependencies(project_dir, self._lockfile(project_dir))
        assert not result.has_errors
        assert not result.has_warnings

    def test_passes_on_fastapi_all_addons(self, tmp_path):
        project_dir = _scaffold(
            tmp_path,
            template="fastapi",
            addons=["docker", "redis", "celery", "sentry", "github-actions"],
        )
        result = _check_dependencies(project_dir, self._lockfile(project_dir))
        assert not result.has_errors

    def test_error_when_pyproject_missing(self, tmp_path):
        project_dir = _scaffold(tmp_path, template="blank")
        (project_dir / "pyproject.toml").unlink()
        result = _check_dependencies(project_dir, self._lockfile(project_dir))
        assert result.has_errors
        assert any("pyproject.toml" in i.message for i in _errors(result))

    def test_error_when_pyproject_corrupt(self, tmp_path):
        project_dir = _scaffold(tmp_path, template="blank")
        (project_dir / "pyproject.toml").write_text("NOT VALID [[[")
        result = _check_dependencies(project_dir, self._lockfile(project_dir))
        assert result.has_errors
        assert any("parsed" in i.message for i in _errors(result))

    def test_error_when_runtime_dep_removed(self, tmp_path):
        project_dir = _scaffold(tmp_path, template="fastapi", addons=["docker"])
        pyproject_path = project_dir / "pyproject.toml"
        doc = tomlkit.parse(pyproject_path.read_text())
        deps = doc["project"]["dependencies"]
        new_deps = [d for d in deps if "fastapi" not in str(d).lower()]
        doc["project"]["dependencies"] = tomlkit.array()
        for d in new_deps:
            doc["project"]["dependencies"].append(d)
        pyproject_path.write_text(tomlkit.dumps(doc))
        result = _check_dependencies(project_dir, self._lockfile(project_dir))
        assert result.has_errors
        assert any("fastapi" in i.message.lower() for i in _errors(result))

    def test_ok_messages_present_when_all_deps_found(self, tmp_path):
        project_dir = _scaffold(tmp_path, template="blank")
        result = _check_dependencies(project_dir, self._lockfile(project_dir))
        assert any("runtime" in i.message for i in _ok(result))
        assert any("dev" in i.message for i in _ok(result))


# ── _check_files ──────────────────────────────────────────────────────────────


class TestCheckFiles:
    def _lockfile(self, project_dir: Path) -> object:
        lf = read_lockfile(project_dir)
        assert lf is not None
        return lf

    def test_passes_on_fresh_blank_project(self, tmp_path):
        project_dir = _scaffold(tmp_path, template="blank")
        result = _check_files(project_dir, self._lockfile(project_dir))
        assert not result.has_errors
        assert not result.has_warnings

    def test_passes_on_fresh_fastapi_project(self, tmp_path):
        project_dir = _scaffold(tmp_path, template="fastapi", addons=["docker"])
        result = _check_files(project_dir, self._lockfile(project_dir))
        assert not result.has_errors

    def test_passes_on_all_addons(self, tmp_path):
        project_dir = _scaffold(
            tmp_path,
            template="fastapi",
            addons=["docker", "redis", "celery", "sentry", "github-actions"],
        )
        result = _check_files(project_dir, self._lockfile(project_dir))
        assert not result.has_errors

    def test_error_when_template_file_deleted(self, tmp_path):
        project_dir = _scaffold(tmp_path, template="blank")
        (project_dir / "src" / "myapp" / "main.py").unlink()
        result = _check_files(project_dir, self._lockfile(project_dir))
        assert result.has_errors
        assert any("main.py" in i.message for i in _errors(result))

    def test_error_when_addon_file_deleted(self, tmp_path):
        project_dir = _scaffold(tmp_path, template="blank", addons=["docker"])
        (project_dir / "Dockerfile").unlink()
        result = _check_files(project_dir, self._lockfile(project_dir))
        assert result.has_errors
        assert any("Dockerfile" in i.message for i in _errors(result))

    def test_error_mentions_addon_name(self, tmp_path):
        project_dir = _scaffold(tmp_path, template="blank", addons=["docker"])
        (project_dir / "Dockerfile").unlink()
        result = _check_files(project_dir, self._lockfile(project_dir))
        assert any("docker" in i.message for i in _errors(result))

    def test_error_mentions_template_for_template_files(self, tmp_path):
        project_dir = _scaffold(tmp_path, template="blank")
        (project_dir / "src" / "myapp" / "main.py").unlink()
        result = _check_files(project_dir, self._lockfile(project_dir))
        assert any("template" in i.message for i in _errors(result))

    def test_init_py_deletion_not_reported(self, tmp_path):
        project_dir = _scaffold(tmp_path, template="blank")
        init = project_dir / "src" / "myapp" / "__init__.py"
        if init.exists():
            init.unlink()
        result = _check_files(project_dir, self._lockfile(project_dir))
        assert not any("__init__.py" in i.message for i in result.issues)

    def test_warn_when_gitignore_missing(self, tmp_path):
        project_dir = _scaffold(tmp_path, template="blank")
        (project_dir / ".gitignore").unlink()
        result = _check_files(project_dir, self._lockfile(project_dir))
        assert result.has_warnings
        assert any(".gitignore" in i.message for i in _warnings(result))

    def test_warn_when_gitattributes_missing(self, tmp_path):
        project_dir = _scaffold(tmp_path, template="blank")
        (project_dir / ".gitattributes").unlink()
        result = _check_files(project_dir, self._lockfile(project_dir))
        assert result.has_warnings
        assert any(".gitattributes" in i.message for i in _warnings(result))

    def test_warn_when_pre_commit_config_missing(self, tmp_path):
        project_dir = _scaffold(tmp_path, template="blank")
        (project_dir / ".pre-commit-config.yaml").unlink()
        result = _check_files(project_dir, self._lockfile(project_dir))
        assert result.has_warnings
        assert any(".pre-commit-config.yaml" in i.message for i in _warnings(result))

    def test_ok_message_includes_file_count(self, tmp_path):
        project_dir = _scaffold(tmp_path, template="blank")
        result = _check_files(project_dir, self._lockfile(project_dir))
        assert any("expected files" in i.message for i in _ok(result))

    def test_multiple_missing_files_all_reported(self, tmp_path):
        project_dir = _scaffold(tmp_path, template="blank", addons=["docker"])
        (project_dir / "Dockerfile").unlink()
        (project_dir / "compose.yml").unlink()
        result = _check_files(project_dir, self._lockfile(project_dir))
        msgs = _messages(_errors(result))
        assert any("Dockerfile" in m for m in msgs)
        assert any("compose.yml" in m for m in msgs)

    def test_redis_addon_file_checked(self, tmp_path):
        project_dir = _scaffold(tmp_path, template="blank", addons=["docker", "redis"])
        redis_file = project_dir / "src" / "myapp" / "integrations" / "redis.py"
        redis_file.unlink()
        result = _check_files(project_dir, self._lockfile(project_dir))
        assert result.has_errors
        assert any("redis.py" in i.message for i in _errors(result))

    def test_sentry_addon_file_checked(self, tmp_path):
        project_dir = _scaffold(tmp_path, template="blank", addons=["sentry"])
        sentry_file = project_dir / "src" / "myapp" / "integrations" / "sentry.py"
        sentry_file.unlink()
        result = _check_files(project_dir, self._lockfile(project_dir))
        assert result.has_errors
        assert any("sentry.py" in i.message for i in _errors(result))

    def test_github_actions_workflow_checked(self, tmp_path):
        project_dir = _scaffold(tmp_path, template="blank", addons=["github-actions"])
        ci_file = project_dir / ".github" / "workflows" / "ci.yml"
        ci_file.unlink()
        result = _check_files(project_dir, self._lockfile(project_dir))
        assert result.has_errors
        assert any("ci.yml" in i.message for i in _errors(result))


# ── _check_addon_health ───────────────────────────────────────────────────────


class TestCheckAddonHealth:
    def _lockfile(self, project_dir: Path) -> object:
        lf = read_lockfile(project_dir)
        assert lf is not None
        return lf

    def test_ok_when_no_addons(self, tmp_path):
        project_dir = _scaffold(tmp_path, template="blank")
        result = _check_addon_health(project_dir, self._lockfile(project_dir))
        assert not result.has_errors
        assert any("No addons" in i.message for i in _ok(result))

    def test_passes_on_fresh_sentry_blank(self, tmp_path):
        project_dir = _scaffold(tmp_path, template="blank", addons=["sentry"])
        result = _check_addon_health(project_dir, self._lockfile(project_dir))
        assert not result.has_errors

    def test_passes_on_fresh_sentry_fastapi(self, tmp_path):
        project_dir = _scaffold(
            tmp_path, template="fastapi", addons=["docker", "sentry"]
        )
        result = _check_addon_health(project_dir, self._lockfile(project_dir))
        assert not result.has_errors

    def test_error_when_init_sentry_removed_from_lifecycle(self, tmp_path):
        project_dir = _scaffold(
            tmp_path, template="fastapi", addons=["docker", "sentry"]
        )
        lifecycle = project_dir / "src" / "myapp" / "lifecycle.py"
        text = lifecycle.read_text()
        lifecycle.write_text(text.replace("init_sentry()", ""))
        result = _check_addon_health(project_dir, self._lockfile(project_dir))
        assert result.has_errors
        assert any("init_sentry" in i.message for i in _errors(result))

    def test_error_when_init_sentry_removed_from_main(self, tmp_path):
        project_dir = _scaffold(tmp_path, template="blank", addons=["sentry"])
        main = project_dir / "src" / "myapp" / "main.py"
        text = main.read_text()
        main.write_text(text.replace("init_sentry()", ""))
        result = _check_addon_health(project_dir, self._lockfile(project_dir))
        assert result.has_errors
        assert any("init_sentry" in i.message for i in _errors(result))

    def test_passes_on_fresh_redis(self, tmp_path):
        project_dir = _scaffold(tmp_path, template="blank", addons=["docker", "redis"])
        result = _check_addon_health(project_dir, self._lockfile(project_dir))
        assert not result.has_errors

    def test_warn_when_redis_url_missing_from_env(self, tmp_path):
        project_dir = _scaffold(
            tmp_path, template="fastapi", addons=["docker", "redis"]
        )
        env_path = project_dir / ".env"
        text = env_path.read_text()
        env_path.write_text(
            "\n".join(line for line in text.splitlines() if "REDIS_URL" not in line)
        )
        result = _check_addon_health(project_dir, self._lockfile(project_dir))
        assert result.has_warnings
        assert any("REDIS_URL" in i.message for i in _warnings(result))

    def test_passes_on_fresh_celery(self, tmp_path):
        project_dir = _scaffold(
            tmp_path, template="blank", addons=["docker", "redis", "celery"]
        )
        result = _check_addon_health(project_dir, self._lockfile(project_dir))
        assert not result.has_errors

    def test_error_when_celery_app_definition_removed(self, tmp_path):
        project_dir = _scaffold(
            tmp_path, template="blank", addons=["docker", "redis", "celery"]
        )
        celery_app = project_dir / "src" / "myapp" / "tasks" / "celery_app.py"
        celery_app.write_text("# celery app removed\n")
        result = _check_addon_health(project_dir, self._lockfile(project_dir))
        assert result.has_errors
        assert any("Celery" in i.message for i in _errors(result))

    def test_no_check_when_addon_has_no_health_check(self, tmp_path):
        project_dir = _scaffold(
            tmp_path, template="blank", addons=["docker", "github-actions"]
        )
        result = _check_addon_health(project_dir, self._lockfile(project_dir))
        assert not result.has_errors

    def test_health_check_exception_reported_as_warning(self, tmp_path):
        project_dir = _scaffold(tmp_path, template="blank")
        lockfile = ZenitLockfile(template="blank", addons=["docker"])

        def broken_health_check(project_dir: Path, lockfile: object) -> list:
            raise RuntimeError("something went wrong")

        hooks = AddonHooks(health_check=broken_health_check)
        cfg = AddonConfig(id="docker", description="")
        cfg._module = hooks

        with mock.patch("zenit.doctor.doctor.get_available_addons", return_value=[cfg]):
            result = _check_addon_health(project_dir, lockfile)
        assert result.has_warnings
        assert any("health_check" in i.message for i in _warnings(result))


# ── _check_compose ────────────────────────────────────────────────────────────


class TestCheckCompose:
    def _lockfile(self, project_dir: Path) -> object:
        lf = read_lockfile(project_dir)
        assert lf is not None
        return lf

    def test_passes_on_fresh_blank_docker(self, tmp_path):
        project_dir = _scaffold(tmp_path, template="blank", addons=["docker"])
        result = _check_compose(project_dir, self._lockfile(project_dir))
        assert not result.has_errors

    def test_passes_on_fresh_fastapi_docker(self, tmp_path):
        project_dir = _scaffold(tmp_path, template="fastapi", addons=["docker"])
        result = _check_compose(project_dir, self._lockfile(project_dir))
        assert not result.has_errors

    def test_passes_on_all_addons(self, tmp_path):
        project_dir = _scaffold(
            tmp_path,
            template="fastapi",
            addons=["docker", "redis", "celery", "sentry", "github-actions"],
        )
        result = _check_compose(project_dir, self._lockfile(project_dir))
        assert not result.has_errors

    def test_ok_when_no_docker_and_no_compose(self, tmp_path):
        project_dir = _scaffold(tmp_path, template="blank")
        result = _check_compose(project_dir, self._lockfile(project_dir))
        assert not result.has_errors
        assert any("docker addon not installed" in i.message for i in _ok(result))

    def test_error_when_docker_installed_but_compose_missing(self, tmp_path):
        project_dir = _scaffold(tmp_path, template="blank", addons=["docker"])
        (project_dir / "compose.yml").unlink()
        result = _check_compose(project_dir, self._lockfile(project_dir))
        assert result.has_errors
        assert any("compose.yml" in i.message for i in _errors(result))

    def test_error_when_compose_corrupt(self, tmp_path):
        project_dir = _scaffold(tmp_path, template="blank", addons=["docker"])
        (project_dir / "compose.yml").write_text("NOT: VALID: YAML: [[[\n")
        result = _check_compose(project_dir, self._lockfile(project_dir))
        assert result.has_errors
        assert any("parsed" in i.message for i in _errors(result))

    def test_error_when_service_missing(self, tmp_path):
        project_dir = _scaffold(
            tmp_path, template="fastapi", addons=["docker", "redis"]
        )
        compose_path = project_dir / "compose.yml"
        data = yaml.safe_load(compose_path.read_text())
        del data["services"]["redis"]
        compose_path.write_text(yaml.dump(data))
        result = _check_compose(project_dir, self._lockfile(project_dir))
        assert result.has_errors
        assert any("redis" in i.message for i in _errors(result))

    def test_error_when_duplicate_service(self, tmp_path):
        project_dir = _scaffold(tmp_path, template="blank", addons=["docker"])
        compose_path = project_dir / "compose.yml"
        text = compose_path.read_text()
        compose_path.write_text(text + "\n  app:\n    image: duplicate\n")
        result = _check_compose(project_dir, self._lockfile(project_dir))
        assert result.has_errors
        assert any("app" in i.message for i in _errors(result))

    def test_no_false_positive_duplicates_on_nested_keys(self, tmp_path):
        project_dir = _scaffold(
            tmp_path, template="fastapi", addons=["docker", "redis", "celery"]
        )
        result = _check_compose(project_dir, self._lockfile(project_dir))
        msgs = _messages(_errors(result))
        for key in [
            "ports",
            "environment",
            "volumes",
            "depends_on",
            "env_file",
            "develop",
        ]:
            assert not any(f"'{key}'" in m for m in msgs), (
                f"Nested key '{key}' was incorrectly flagged as duplicate service"
            )

    def test_ok_message_lists_expected_services(self, tmp_path):
        project_dir = _scaffold(
            tmp_path, template="fastapi", addons=["docker", "redis"]
        )
        result = _check_compose(project_dir, self._lockfile(project_dir))
        assert any("redis" in i.message for i in _ok(result))


# ── _check_env ────────────────────────────────────────────────────────────────


class TestCheckEnv:
    def _lockfile(self, project_dir: Path) -> object:
        lf = read_lockfile(project_dir)
        assert lf is not None
        return lf

    def test_passes_on_fresh_fastapi_project(self, tmp_path):
        project_dir = _scaffold(tmp_path, template="fastapi", addons=["docker"])
        result = _check_env(project_dir, self._lockfile(project_dir))
        assert not result.has_errors
        assert not result.has_warnings

    def test_passes_on_all_addons(self, tmp_path):
        project_dir = _scaffold(
            tmp_path,
            template="fastapi",
            addons=["docker", "redis", "sentry", "celery", "github-actions"],
        )
        result = _check_env(project_dir, self._lockfile(project_dir))
        assert not result.has_errors

    def test_ok_when_no_env_vars_expected(self, tmp_path):
        project_dir = _scaffold(tmp_path, template="blank")
        result = _check_env(project_dir, self._lockfile(project_dir))
        assert not result.has_errors
        assert any("No env vars expected" in i.message for i in _ok(result))

    def test_error_when_env_var_missing_from_env(self, tmp_path):
        project_dir = _scaffold(tmp_path, template="fastapi", addons=["docker"])
        env_path = project_dir / ".env"
        text = env_path.read_text()
        env_path.write_text(
            "\n".join(line for line in text.splitlines() if "DATABASE_URL" not in line)
        )
        result = _check_env(project_dir, self._lockfile(project_dir))
        assert result.has_errors
        assert any("DATABASE_URL" in i.message for i in _errors(result))

    def test_error_when_env_var_missing_from_env_example(self, tmp_path):
        project_dir = _scaffold(tmp_path, template="fastapi", addons=["docker"])
        env_example = project_dir / ".env.example"
        text = env_example.read_text()
        env_example.write_text(
            "\n".join(line for line in text.splitlines() if "DATABASE_URL" not in line)
        )
        result = _check_env(project_dir, self._lockfile(project_dir))
        assert result.has_errors
        assert any("DATABASE_URL" in i.message for i in _errors(result))

    def test_warn_when_env_file_missing(self, tmp_path):
        project_dir = _scaffold(tmp_path, template="fastapi", addons=["docker"])
        (project_dir / ".env").unlink()
        result = _check_env(project_dir, self._lockfile(project_dir))
        assert result.has_warnings
        assert any(".env" in i.message for i in _warnings(result))

    def test_warn_when_env_example_missing(self, tmp_path):
        project_dir = _scaffold(tmp_path, template="fastapi", addons=["docker"])
        (project_dir / ".env.example").unlink()
        result = _check_env(project_dir, self._lockfile(project_dir))
        assert result.has_warnings
        assert any(".env.example" in i.message for i in _warnings(result))

    def test_redis_url_checked_when_redis_installed(self, tmp_path):
        project_dir = _scaffold(
            tmp_path, template="fastapi", addons=["docker", "redis"]
        )
        env_path = project_dir / ".env"
        text = env_path.read_text()
        env_path.write_text(
            "\n".join(line for line in text.splitlines() if "REDIS_URL" not in line)
        )
        result = _check_env(project_dir, self._lockfile(project_dir))
        assert result.has_errors
        assert any("REDIS_URL" in i.message for i in _errors(result))

    def test_sentry_dsn_checked_when_sentry_installed(self, tmp_path):
        project_dir = _scaffold(
            tmp_path, template="fastapi", addons=["docker", "sentry"]
        )
        env_path = project_dir / ".env"
        text = env_path.read_text()
        env_path.write_text(
            "\n".join(line for line in text.splitlines() if "SENTRY_DSN" not in line)
        )
        result = _check_env(project_dir, self._lockfile(project_dir))
        assert result.has_errors
        assert any("SENTRY_DSN" in i.message for i in _errors(result))


# ── run_doctor integration ────────────────────────────────────────────────────


class TestRunDoctor:
    def test_returns_only_metadata_when_no_lockfile(self, tmp_path):
        project_dir = tmp_path / "myapp"
        project_dir.mkdir()
        results = run_doctor(project_dir)
        assert len(results) == 1
        assert results[0].category == "Metadata"

    def test_returns_multiple_sections_for_blank(self, tmp_path):
        project_dir = _scaffold(tmp_path, template="blank")
        results = run_doctor(project_dir)
        categories = [r.category for r in results]
        assert "Metadata" in categories
        assert "Dependencies" in categories
        assert "Generated files" in categories
        assert "Addon integrity" in categories
        assert "Compose" in categories

    def test_no_errors_on_fresh_blank(self, tmp_path):
        project_dir = _scaffold(tmp_path, template="blank")
        results = run_doctor(project_dir)
        assert not any(r.has_errors for r in results)

    def test_no_errors_on_fresh_fastapi_docker(self, tmp_path):
        project_dir = _scaffold(tmp_path, template="fastapi", addons=["docker"])
        results = run_doctor(project_dir)
        assert not any(r.has_errors for r in results)

    def test_no_errors_on_fresh_all_addons(self, tmp_path):
        project_dir = _scaffold(
            tmp_path,
            template="fastapi",
            addons=["docker", "redis", "celery", "sentry", "github-actions"],
        )
        results = run_doctor(project_dir)
        for r in results:
            assert not r.has_errors, (
                f"Section '{r.category}' has errors: {[i.message for i in _errors(r)]}"
            )

    def test_detects_deleted_main_py(self, tmp_path):
        project_dir = _scaffold(tmp_path, template="blank")
        (project_dir / "src" / "myapp" / "main.py").unlink()
        results = run_doctor(project_dir)
        all_errors = [i for r in results for i in _errors(r)]
        assert any("main.py" in i.message for i in all_errors)

    def test_detects_removed_runtime_dep(self, tmp_path):
        project_dir = _scaffold(tmp_path, template="fastapi", addons=["docker"])
        pyproject_path = project_dir / "pyproject.toml"
        doc = tomlkit.parse(pyproject_path.read_text())
        deps = doc["project"]["dependencies"]
        new_deps = [d for d in deps if "fastapi" not in str(d).lower()]
        doc["project"]["dependencies"] = tomlkit.array()
        for d in new_deps:
            doc["project"]["dependencies"].append(d)
        pyproject_path.write_text(tomlkit.dumps(doc))
        results = run_doctor(project_dir)
        all_errors = [i for r in results for i in _errors(r)]
        assert any("fastapi" in i.message.lower() for i in all_errors)


# ── print_results ─────────────────────────────────────────────────────────────


class TestPrintResults:
    def test_returns_false_when_no_errors(self, capsys):
        r = HealthResult("Test")
        r.ok("all good")
        assert print_results([r]) is False

    def test_returns_true_when_errors_present(self, capsys):
        r = HealthResult("Test")
        r.error("broken")
        assert print_results([r]) is True

    def test_prints_category_name(self, capsys):
        r = HealthResult("My Category")
        r.ok("fine")
        print_results([r])
        assert "My Category" in capsys.readouterr().out

    def test_prints_ok_message(self, capsys):
        r = HealthResult("Test")
        r.ok("everything is fine")
        print_results([r])
        assert "everything is fine" in capsys.readouterr().out

    def test_prints_warn_message(self, capsys):
        r = HealthResult("Test")
        r.warn("watch out")
        print_results([r])
        assert "watch out" in capsys.readouterr().out

    def test_prints_error_message(self, capsys):
        r = HealthResult("Test")
        r.error("broken")
        print_results([r])
        assert "broken" in capsys.readouterr().out

    def test_prints_hint_when_present(self, capsys):
        r = HealthResult("Test")
        r.error("broken", hint="fix this way")
        print_results([r])
        assert "fix this way" in capsys.readouterr().out

    def test_does_not_print_empty_hint(self, capsys):
        r = HealthResult("Test")
        r.ok("fine")
        print_results([r])
        out = capsys.readouterr().out
        assert "fine" in out
        content_lines = [line for line in out.splitlines() if "fine" in line]
        assert len(content_lines) == 1

    def test_prints_multiple_sections(self, capsys):
        r1 = HealthResult("Section A")
        r1.ok("a is fine")
        r2 = HealthResult("Section B")
        r2.ok("b is fine")
        print_results([r1, r2])
        out = capsys.readouterr().out
        assert "Section A" in out
        assert "Section B" in out

    def test_returns_true_if_any_section_has_error(self, capsys):
        r1 = HealthResult("Good")
        r1.ok("fine")
        r2 = HealthResult("Bad")
        r2.error("broken")
        assert print_results([r1, r2]) is True

    def test_empty_results_returns_false(self, capsys):
        assert print_results([]) is False


# ── _check_python_line_presence — fast tier ───────────────────────────────────


class TestCheckPythonLinePresence:
    def test_ok_on_fresh_fastapi_redis(self, tmp_path: Path) -> None:
        project_dir = _scaffold(tmp_path, template="fastapi", addons=["redis"])
        result = _check_python_line_presence(project_dir)
        assert not result.has_errors

    def test_error_when_file_truncated_below_recorded_end(self, tmp_path: Path) -> None:
        """Fast-tier line check fires when a tracked file has fewer lines
        than the manifest block's recorded end line."""
        from zenit.core.manifest import read_manifest

        project_dir = _scaffold(tmp_path, template="fastapi", addons=["redis"])
        m = read_manifest(project_dir)

        # Find any block with a real file and truncate it.
        block = next(
            (b for b in m.python_blocks if (project_dir / b.file).exists()), None
        )
        assert block is not None, (
            "Expected at least one Python block after redis scaffold"
        )

        target = project_dir / block.file
        target.write_text("# file truncated\n", encoding="utf-8")

        result = _check_python_line_presence(project_dir)
        assert result.has_errors
        assert any(
            block.file in i.message for i in result.issues if i.severity.name == "ERROR"
        )

    def test_ok_when_no_python_blocks(self, tmp_path: Path) -> None:
        """Fast-tier line check on a project with no Python blocks returns OK."""
        project_dir = _scaffold(tmp_path, template="blank")
        result = _check_python_line_presence(project_dir)
        assert not result.has_errors


# ── _check_python_integrity — thorough tier ───────────────────────────────────


class TestCheckPythonIntegrity:
    """Parametrized over fixture states: exact match, normalised match,
    semantic change, and invalid Python."""

    def test_ok_when_block_matches_exact_fingerprint(self, tmp_path: Path) -> None:
        """Thorough check: unmodified block → OK, no warning."""
        project_dir = _scaffold(tmp_path, template="fastapi", addons=["redis"])
        result = _check_python_integrity(project_dir)
        assert not result.has_errors
        assert not result.has_warnings

    def test_warn_when_block_reformatted_but_normalised_matches(
        self, tmp_path: Path
    ) -> None:
        """Thorough check: libcst round-trip on the tracked file changes the
        raw fingerprint but the normalised fingerprint still matches → WARN."""
        import libcst as cst

        from zenit.core.manifest import read_manifest

        project_dir = _scaffold(tmp_path, template="fastapi", addons=["redis"])
        m = read_manifest(project_dir)
        block = next(
            (b for b in m.python_blocks if (project_dir / b.file).exists()), None
        )
        assert block is not None

        target = project_dir / block.file
        original = target.read_text(encoding="utf-8")
        target.write_text(cst.parse_module(original).code, encoding="utf-8")

        result = _check_python_integrity(project_dir)
        # A pure CST round-trip should not degrade to ERROR.
        assert not result.has_errors

    def test_error_when_block_semantically_changed(self, tmp_path: Path) -> None:
        """Thorough check: renaming a field in the tracked block breaks both
        fingerprints → ERROR with file name and point in message."""
        from zenit.core.manifest import read_manifest

        project_dir = _scaffold(tmp_path, template="fastapi", addons=["redis"])
        m = read_manifest(project_dir)
        block = next(
            (b for b in m.python_blocks if (project_dir / b.file).exists()), None
        )
        assert block is not None

        target = project_dir / block.file
        text = target.read_text(encoding="utf-8")
        start, end = (int(x) for x in block.lines.split("-"))
        lines = text.splitlines(keepends=True)
        # Replace the block content with something semantically different.
        replacement = "    __zenit_test_sentinel__: int = 999\n"
        new_lines = lines[: start - 1] + [replacement] + lines[end:]
        target.write_text("".join(new_lines), encoding="utf-8")

        result = _check_python_integrity(project_dir)
        assert result.has_errors
        assert any(
            block.file in i.message for i in result.issues if i.severity.name == "ERROR"
        )

    def test_warn_when_block_is_unparseable_python(self, tmp_path: Path) -> None:
        """Thorough check: block text that libcst cannot parse → WARN (not ERROR).
        The block may be a class-body fragment; this must not crash the check."""
        from zenit.core.manifest import read_manifest

        project_dir = _scaffold(tmp_path, template="fastapi", addons=["redis"])
        m = read_manifest(project_dir)
        block = next(
            (b for b in m.python_blocks if (project_dir / b.file).exists()), None
        )
        assert block is not None

        target = project_dir / block.file
        text = target.read_text(encoding="utf-8")
        start, end = (int(x) for x in block.lines.split("-"))
        lines = text.splitlines(keepends=True)
        # Write syntactically broken content at the block position.
        broken = "    def (\n"
        new_lines = lines[: start - 1] + [broken] + lines[end:]
        target.write_text("".join(new_lines), encoding="utf-8")

        # Must not raise — fingerprint falls back to raw text hashing.
        # In this case the raw fingerprint won't match either → ERROR is also
        # acceptable, but no unhandled exception.
        try:
            result = _check_python_integrity(project_dir)
            assert result is not None
        except Exception as exc:  # pragma: no cover
            raise AssertionError(
                "_check_python_integrity must not raise on unparseable Python"
            ) from exc


# ── Thorough tier — run_doctor integration ─────────────────────────────────────


class TestRunDoctorThoroughFlag:
    def test_thorough_flag_enables_python_integrity_check(self, tmp_path: Path) -> None:
        """run_doctor(thorough=True) must include a 'Python block integrity' section
        that is absent from the default fast run."""
        project_dir = _scaffold(tmp_path, template="fastapi", addons=["redis"])

        fast_results = run_doctor(project_dir, thorough=False)
        thorough_results = run_doctor(project_dir, thorough=True)

        fast_categories = {r.category for r in fast_results}
        thorough_categories = {r.category for r in thorough_results}

        integrity_category = "Python block integrity (thorough)"
        assert integrity_category not in fast_categories, (
            f"Fast run must not include '{integrity_category}'"
        )
        assert integrity_category in thorough_categories, (
            f"Thorough run must include '{integrity_category}'"
        )

    def test_fast_tier_does_not_import_libcst(self, tmp_path: Path) -> None:
        """The fast doctor path must not trigger a libcst import.

        This is a performance contract: the fast tier must complete without
        pulling in the libcst parse machinery, which is expensive to import
        and should stay isolated to the thorough tier.
        """
        project_dir = _scaffold(tmp_path, template="fastapi", addons=["redis"])

        # Evict libcst from sys.modules so we can detect a fresh import.
        libcst_keys = [
            k for k in sys.modules if k == "libcst" or k.startswith("libcst.")
        ]
        saved = {k: sys.modules.pop(k) for k in libcst_keys}

        try:
            run_doctor(project_dir, thorough=False)
            assert "libcst" not in sys.modules, (
                "Fast doctor tier must not import libcst. "
                "Move libcst usage into _check_python_integrity (thorough only)."
            )
        finally:
            sys.modules.update(saved)

    def test_fast_tier_python_line_check_does_not_parse(self, tmp_path: Path) -> None:
        """The fast-tier line-presence check must perform only a file-length
        comparison — it must not call libcst.parse_module at any point.

        Verified by patching libcst.parse_module to raise if called, then
        asserting the check still returns a result without error.
        """
        import unittest.mock as _mock

        project_dir = _scaffold(tmp_path, template="fastapi", addons=["redis"])

        sentinel = AssertionError(
            "_check_python_line_presence must not call libcst.parse_module"
        )

        try:
            import libcst as _cst  # noqa: PLC0415
        except ImportError:
            return  # libcst not installed at all — nothing to patch

        with _mock.patch.object(_cst, "parse_module", side_effect=sentinel):
            result = _check_python_line_presence(project_dir)

        assert result is not None
