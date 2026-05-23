"""Shared pytest fixtures and helpers."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from click.exceptions import Exit as ClickExit

from zenit.addons._registry import get_available_addons
from zenit.core._apply_loader import load_apply
from zenit.core.apply import apply_contributions
from zenit.core.collect import collect_all
from zenit.core.context import Context
from zenit.core.filesystem import RealFileSystem
from zenit.core.generate import generate_all
from zenit.core.git import init
from zenit.core.lockfile import write_lockfile
from zenit.core.render import build_render_vars
from zenit.templates._load_config import load_template_config


def raises_exit(code: int = 1) -> pytest.ExceptionInfo[ClickExit]:
    """Context manager that expects a ``typer.Exit(code)`` to be raised."""
    return pytest.raises(ClickExit, match="")


class ExitAssertion:
    """Context manager that asserts a ``typer.Exit(1)`` was raised."""

    def __enter__(self) -> ExitAssertion:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> bool:
        if exc_type is None:
            raise AssertionError(
                "Expected a typer.Exit to be raised but nothing was raised"
            )
        if not issubclass(exc_type, ClickExit):
            return False
        assert isinstance(exc_val, ClickExit)
        assert exc_val.exit_code == 1, f"Expected exit code 1, got {exc_val.exit_code}"
        return True


ZENIT_ROOT = Path(__file__).parent.parent / "src" / "zenit"


def write_test_manifest(
    project_dir: Path,
    addons: list[str],
    render_vars: dict[str, object],
) -> None:
    """Write manifest entries for all *addons* — mirrors real ``zenit add`` flow.

    Call this after ``generate_all()`` in test ``_scaffold`` helpers so that
    ``remove_addon`` can read manifest entries instead of relying on
    ``addon_cfg`` directly.

    Reads any existing manifest (``apply_contributions`` may have already
    recorded ``python_blocks``) and appends addon-owned entries to it.
    """
    from zenit.addons._registry import get_available_addons
    from zenit.core.manifest import (
        read_manifest,
        record_addon_manifest_entries,
        write_manifest,
    )
    from zenit.core.render import make_env

    manifest = read_manifest(project_dir)
    string_env = make_env()
    available = get_available_addons()
    docker_active = "docker" in addons
    for addon_id in addons:
        cfg = next(c for c in available if c.id == addon_id)
        record_addon_manifest_entries(
            manifest, cfg, string_env, render_vars, docker_active=docker_active
        )
    write_manifest(project_dir, manifest)


@pytest.fixture
def scaffold_project(tmp_path: Path) -> Callable[[str, str, list[str]], Path]:
    """Scaffold a project into a temporary directory and return the project path.

    Runs the full pipeline: common files, template + addon contributions,
    render, generate, manifest, git init/commit, and lockfile.  The project is
    placed inside *tmp_path* which is scoped to the individual test function.
    """

    def _scaffold(name: str, template: str, addons: list[str]) -> Path:
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
        fs = RealFileSystem(project_dir)

        load_apply(ZENIT_ROOT / "templates" / "_common" / "apply.py")(ctx, fs)

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
        write_lockfile(project_dir, template, addons)

        return project_dir

    return _scaffold
