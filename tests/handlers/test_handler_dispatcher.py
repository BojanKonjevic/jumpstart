"""Unit tests for zenit.core.handlers.base.HandlerDispatcher.

Covers: correct handler returned per file type, ValueError on unknown
extension, and Python-wins priority assertion.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from zenit.core.handlers.base import HandlerDispatcher
from zenit.core.handlers.env_handler import EnvHandler
from zenit.core.handlers.justfile_handler import JustfileHandler
from zenit.core.handlers.python_handler import PythonHandler
from zenit.core.handlers.toml_handler import TomlHandler
from zenit.core.handlers.yaml_handler import YamlHandler

# ── helpers ───────────────────────────────────────────────────────────────────


def _dispatch(path: str) -> object:
    return HandlerDispatcher()._get(Path(path))


# ── dispatch by file type ─────────────────────────────────────────────────────


def test_dispatch_python_handler_for_py() -> None:
    assert isinstance(_dispatch("foo.py"), PythonHandler)


def test_dispatch_env_handler_for_env() -> None:
    assert isinstance(_dispatch(".env"), EnvHandler)


def test_dispatch_env_handler_for_env_example() -> None:
    assert isinstance(_dispatch(".env.example"), EnvHandler)


def test_dispatch_yaml_handler_for_yml() -> None:
    assert isinstance(_dispatch("compose.yml"), YamlHandler)


def test_dispatch_yaml_handler_for_yaml() -> None:
    assert isinstance(_dispatch("config.yaml"), YamlHandler)


def test_dispatch_toml_handler_for_toml() -> None:
    assert isinstance(_dispatch("pyproject.toml"), TomlHandler)


def test_dispatch_justfile_handler_for_justfile() -> None:
    assert isinstance(_dispatch("justfile"), JustfileHandler)


def test_dispatch_justfile_handler_nested_path() -> None:
    assert isinstance(_dispatch("project/justfile"), JustfileHandler)


def test_dispatch_raises_value_error_for_unknown() -> None:
    with pytest.raises(ValueError) as exc_info:
        _dispatch("archive.tar.gz")
    assert "archive.tar.gz" in str(exc_info.value)


def test_dispatch_python_wins_over_other_handlers() -> None:
    # A .py file must never be claimed by env, yaml, toml, or justfile handlers.
    # PythonHandler is first in the priority list; this test pins that invariant.
    d = HandlerDispatcher()
    handler = d._get(Path("settings.py"))
    assert isinstance(handler, PythonHandler), (
        f"Expected PythonHandler for .py files, got {type(handler).__name__}. "
        "Check handler priority order in HandlerDispatcher.__init__."
    )
