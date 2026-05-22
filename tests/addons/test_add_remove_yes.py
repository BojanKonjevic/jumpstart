"""Tests for the ``--yes`` flag on add/remove functions.

These tests call the functions directly (not via CLI) and verify that
``yes=True`` skips the confirmation prompt without needing ``suppress_stdin()``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import ZENIT_ROOT

from zenit.addons._registry import get_available_addons
from zenit.addons.add import add_addon
from zenit.addons.remove import remove_addon
from zenit.core._apply_loader import load_apply
from zenit.core.apply import apply_contributions
from zenit.core.collect import collect_all
from zenit.core.context import Context
from zenit.core.generate import generate_all
from zenit.core.git import init
from zenit.core.lockfile import write_lockfile
from zenit.core.render import build_render_vars
from zenit.templates._load_config import load_template_config


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

    load_apply(ZENIT_ROOT / "templates" / "_common" / "apply.py")(ctx)

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
        ctx, contributions, template_config.injection_points, render_vars
    )
    generate_all(ctx, contributions)
    init(project_dir)
    write_lockfile(project_dir, template, addons)
    return project_dir


def test_add_with_yes_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """add_addon(..., yes=True) skips confirmation without suppress_stdin()."""
    project_dir = _scaffold(tmp_path, "myapp", "blank", [])
    monkeypatch.chdir(project_dir)

    add_addon("sentry", yes=True)

    assert (project_dir / "src" / "myapp" / "integrations" / "sentry.py").exists()


def test_remove_with_yes_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """remove_addon(..., yes=True) skips confirmation without suppress_stdin()."""
    project_dir = _scaffold(tmp_path, "myapp", "blank", ["sentry"])
    monkeypatch.chdir(project_dir)

    remove_addon("sentry", yes=True, project_dir=project_dir)

    assert not (project_dir / "src" / "myapp" / "integrations" / "sentry.py").exists()
