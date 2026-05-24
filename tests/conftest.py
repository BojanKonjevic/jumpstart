"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from helpers import scaffold_project_at


@pytest.fixture
def scaffold_project(tmp_path: Path) -> Callable[[str, str, list[str]], Path]:
    """Scaffold a project into a temporary directory and return the project path.

    Runs the full pipeline.  The project is placed inside *tmp_path* which is
    scoped to the individual test function.
    """

    def _scaffold(name: str, template: str, addons: list[str]) -> Path:
        project_dir = tmp_path / name
        project_dir.mkdir(parents=True)
        return scaffold_project_at(project_dir, name, template, addons)

    return _scaffold


@pytest.fixture(scope="class")
def class_tmp_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Return a temporary directory scoped to the test class."""
    return tmp_path_factory.mktemp("class-scaffold")
