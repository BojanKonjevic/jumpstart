"""Tests for zenit.deps — dependency injection into pyproject.toml.

Covers inject_deps and the _dep_package_name helper for all relevant cases:
adding new deps, skipping existing ones, handling both [dependency-groups]
and [project.optional-dependencies] dev layouts, and edge cases.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from zenit.core.deps import inject_deps
from zenit.core.manifest import dep_package_name

# ── dep_package_name ───────────────────────────────────────────────────────────


def test_dep_package_name_simple():
    assert dep_package_name("redis") == "redis"


def test_dep_package_name_with_version_specifier():
    assert dep_package_name("redis>=5") == "redis"


def test_dep_package_name_with_extras():
    assert dep_package_name("celery[redis]>=5") == "celery"


def test_dep_package_name_with_extras_no_version():
    assert dep_package_name("sentry-sdk[fastapi]") == "sentry_sdk"


def test_dep_package_name_lowercased():
    assert dep_package_name("FastAPI") == "fastapi"


def test_dep_package_name_with_hyphen():
    assert dep_package_name("python-dotenv>=1.0") == "python_dotenv"


def test_dep_package_name_complex_extras():
    assert dep_package_name("fakeredis[aioredis]") == "fakeredis"


def test_dep_package_name_with_tilde_specifier():
    assert dep_package_name("mypy~=1.0") == "mypy"


def test_dep_package_name_empty_string():
    # degenerate input — should not raise
    result = dep_package_name("")
    assert isinstance(result, str)


# ── helpers ───────────────────────────────────────────────────────────────────


def _write_pyproject(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "pyproject.toml"
    p.write_text(content, encoding="utf-8")
    return p


def _minimal_pyproject(
    deps: list[str] | None = None,
    dev_deps: list[str] | None = None,
    use_optional: bool = False,
) -> str:
    """Return a pyproject.toml string matching the format produced by
    generate/pyproject.toml.j2.

    deps and dev_deps must each contain at least one entry when non-None so
    that tomlkit's get() returns a live array reference rather than a copy.
    Real generated projects always satisfy this (they always have python-dotenv
    as a runtime dep and pytest as a dev dep at minimum).
    """
    # Always include a seed dep so tomlkit hands back a live reference.
    runtime = list(deps) if deps is not None else ["python-dotenv"]
    dep_lines = "".join(f'  "{d}",\n' for d in runtime)
    dep_block = f"dependencies = [\n{dep_lines}]"

    if use_optional:
        devs = list(dev_deps) if dev_deps is not None else ["pytest>=8"]
        dev_lines = "".join(f'  "{d}",\n' for d in devs)
        dev_block = f"\n[project.optional-dependencies]\ndev = [\n{dev_lines}]\n"
        return f'[project]\nname = "myapp"\n{dep_block}\n{dev_block}'
    else:
        devs = list(dev_deps) if dev_deps is not None else ["pytest>=8"]
        dev_lines = "".join(f'  "{d}",\n' for d in devs)
        dev_block = f"\n[dependency-groups]\ndev = [\n{dev_lines}]\n"
        return f'[project]\nname = "myapp"\n{dep_block}\n{dev_block}'


# ── inject_deps — basic runtime deps ─────────────────────────────────────────


def test_inject_deps_adds_new_runtime_dep(tmp_path):
    _write_pyproject(tmp_path, _minimal_pyproject())
    added, added_dev = inject_deps(tmp_path, ["redis>=5"], [])
    assert "redis>=5" in added
    assert added_dev == []
    text = (tmp_path / "pyproject.toml").read_text()
    assert "redis>=5" in text


def test_inject_deps_adds_multiple_runtime_deps(tmp_path):
    _write_pyproject(tmp_path, _minimal_pyproject())
    added, _ = inject_deps(tmp_path, ["redis>=5", "hiredis"], [])
    assert "redis>=5" in added
    assert "hiredis" in added
    text = (tmp_path / "pyproject.toml").read_text()
    assert "redis>=5" in text
    assert "hiredis" in text


def test_inject_deps_skips_already_present_runtime_dep(tmp_path):
    _write_pyproject(tmp_path, _minimal_pyproject(deps=["python-dotenv", "redis>=5"]))
    added, _ = inject_deps(tmp_path, ["redis>=5"], [])
    assert added == []
    text = (tmp_path / "pyproject.toml").read_text()
    assert text.count("redis>=5") == 1


def test_inject_deps_skips_dep_with_different_specifier_same_name(tmp_path):
    # "redis>=4" already present — "redis>=5" skipped (same pkg name)
    _write_pyproject(tmp_path, _minimal_pyproject(deps=["python-dotenv", "redis>=4"]))
    added, _ = inject_deps(tmp_path, ["redis>=5"], [])
    assert added == []


def test_inject_deps_adds_dep_with_extras(tmp_path):
    _write_pyproject(tmp_path, _minimal_pyproject())
    added, _ = inject_deps(tmp_path, ["celery[redis]>=5"], [])
    assert "celery[redis]>=5" in added
    text = (tmp_path / "pyproject.toml").read_text()
    assert "celery[redis]>=5" in text


def test_inject_deps_does_not_add_existing_dep_with_extras(tmp_path):
    # "celery" name already present via "celery[redis]>=5"
    _write_pyproject(
        tmp_path, _minimal_pyproject(deps=["python-dotenv", "celery[redis]>=5"])
    )
    added, _ = inject_deps(tmp_path, ["celery>=5"], [])
    assert added == []


def test_inject_deps_returns_empty_lists_when_nothing_to_add(tmp_path):
    _write_pyproject(
        tmp_path, _minimal_pyproject(deps=["python-dotenv", "fastapi", "uvicorn"])
    )
    added, added_dev = inject_deps(tmp_path, ["fastapi", "uvicorn"], [])
    assert added == []
    assert added_dev == []


def test_inject_deps_creates_dependencies_key_when_missing(
    tmp_path: Path,
) -> None:
    """pyproject.toml has [project] but no dependencies key at all."""
    _write_pyproject(
        tmp_path,
        '[project]\nname = "myapp"\n',
    )
    added, _ = inject_deps(tmp_path, ["sentry-sdk[fastapi]", "python-dotenv"], [])
    assert "sentry-sdk[fastapi]" in added
    assert "python-dotenv" in added
    text = (tmp_path / "pyproject.toml").read_text()
    assert "sentry-sdk[fastapi]" in text
    assert "python-dotenv" in text


def test_inject_deps_creates_project_table_when_missing(tmp_path: Path) -> None:
    """pyproject.toml has no [project] table at all (e.g. bare config)."""
    _write_pyproject(tmp_path, "[tool.uv]\npackage = true\n")
    added, _ = inject_deps(tmp_path, ["sentry-sdk", "python-dotenv"], [])
    assert "sentry-sdk" in added
    text = (tmp_path / "pyproject.toml").read_text()
    assert "sentry-sdk" in text
    assert "[project]" in text


def test_inject_deps_writes_to_table_without_dotenv_seed(tmp_path: Path) -> None:
    """pyproject.toml has [project] dependencies but no python-dotenv seed.

    This simulates a Copier-generated project that ships with some deps
    already present but not the ones the addon needs.
    """
    _write_pyproject(
        tmp_path,
        '[project]\nname = "myapp"\ndependencies = ["fastapi>=0.100"]\n'
        '\n[dependency-groups]\ndev = ["pytest>=8"]\n',
    )
    added, added_dev = inject_deps(
        tmp_path, ["sentry-sdk[fastapi]", "python-dotenv"], ["fakeredis"]
    )
    assert "sentry-sdk[fastapi]" in added
    assert "python-dotenv" in added
    assert "fakeredis" in added_dev
    text = (tmp_path / "pyproject.toml").read_text()
    assert "sentry-sdk[fastapi]" in text
    assert "python-dotenv" in text
    assert "fakeredis" in text


# ── inject_deps — dev deps via [dependency-groups] ───────────────────────────


def test_inject_dev_deps_creates_dev_key_when_missing(tmp_path: Path) -> None:
    """[dependency-groups] exists but dev key does not."""
    _write_pyproject(
        tmp_path,
        '[project]\nname = "myapp"\ndependencies = ["python-dotenv"]\n'
        "\n[dependency-groups]\n",
    )
    _, added_dev = inject_deps(tmp_path, [], ["fakeredis"])
    assert "fakeredis" in added_dev
    text = (tmp_path / "pyproject.toml").read_text()
    assert "[dependency-groups]" in text
    assert "fakeredis" in text


def test_inject_dev_deps_adds_to_dependency_groups(tmp_path):
    _write_pyproject(tmp_path, _minimal_pyproject())
    _, added_dev = inject_deps(tmp_path, [], ["fakeredis"])
    assert "fakeredis" in added_dev
    text = (tmp_path / "pyproject.toml").read_text()
    assert "fakeredis" in text


def test_inject_dev_deps_skips_existing_in_dependency_groups(tmp_path):
    _write_pyproject(tmp_path, _minimal_pyproject(dev_deps=["pytest>=8", "httpx"]))
    _, added_dev = inject_deps(tmp_path, [], ["pytest>=8"])
    assert added_dev == []


def test_inject_dev_deps_case_insensitive_name_matching(tmp_path):
    _write_pyproject(tmp_path, _minimal_pyproject(dev_deps=["Pytest>=8", "httpx"]))
    _, added_dev = inject_deps(tmp_path, [], ["pytest>=8"])
    assert added_dev == []


# ── inject_deps — dev deps via [project.optional-dependencies] ───────────────


def test_inject_dev_deps_adds_to_optional_dependencies(tmp_path):
    _write_pyproject(
        tmp_path, _minimal_pyproject(dev_deps=["pytest>=8"], use_optional=True)
    )
    _, added_dev = inject_deps(tmp_path, [], ["fakeredis"])
    assert "fakeredis" in added_dev
    text = (tmp_path / "pyproject.toml").read_text()
    assert "fakeredis" in text


def test_inject_dev_deps_skips_existing_in_optional_dependencies(tmp_path):
    _write_pyproject(
        tmp_path,
        _minimal_pyproject(dev_deps=["pytest>=8", "httpx"], use_optional=True),
    )
    _, added_dev = inject_deps(tmp_path, [], ["pytest>=8"])
    assert added_dev == []


def test_inject_dev_deps_no_dev_group_present_still_works(tmp_path):
    # No dev group at all — dev deps silently skipped, runtime deps still added
    _write_pyproject(
        tmp_path,
        '[project]\nname = "myapp"\ndependencies = [\n  "python-dotenv",\n]\n',
    )
    added, added_dev = inject_deps(tmp_path, ["redis"], ["fakeredis"])
    assert "redis" in added
    assert added_dev == []


# ── inject_deps — combined runtime + dev ─────────────────────────────────────


def test_inject_deps_adds_both_runtime_and_dev(tmp_path):
    _write_pyproject(tmp_path, _minimal_pyproject())
    added, added_dev = inject_deps(tmp_path, ["redis>=5"], ["fakeredis"])
    assert "redis>=5" in added
    assert "fakeredis" in added_dev


def test_inject_deps_partial_skip_partial_add(tmp_path):
    _write_pyproject(
        tmp_path,
        _minimal_pyproject(
            deps=["python-dotenv", "fastapi"],
            dev_deps=["pytest>=8", "httpx"],
        ),
    )
    added, added_dev = inject_deps(
        tmp_path, ["fastapi", "uvicorn"], ["pytest>=8", "mypy"]
    )
    assert "fastapi" not in added
    assert "uvicorn" in added
    assert "pytest>=8" not in added_dev
    assert "mypy" in added_dev


# ── inject_deps — file not found ─────────────────────────────────────────────


def test_inject_deps_raises_when_pyproject_missing(tmp_path):
    with pytest.raises(FileNotFoundError, match="pyproject.toml"):
        inject_deps(tmp_path, ["redis"], [])


# ── inject_deps — round-trip correctness ─────────────────────────────────────


def test_inject_deps_preserves_existing_content(tmp_path):
    _write_pyproject(
        tmp_path,
        _minimal_pyproject(
            deps=["python-dotenv", "fastapi"],
            dev_deps=["pytest>=8"],
        ),
    )
    inject_deps(tmp_path, ["redis>=5"], ["fakeredis"])
    text = (tmp_path / "pyproject.toml").read_text()
    assert "fastapi" in text
    assert "pytest>=8" in text
    assert "redis>=5" in text
    assert "fakeredis" in text


def test_inject_deps_preserves_toml_structure(tmp_path):
    """After injection the file must still be valid TOML."""
    _write_pyproject(tmp_path, _minimal_pyproject())
    inject_deps(tmp_path, ["redis>=5", "hiredis"], ["fakeredis"])
    with open(tmp_path / "pyproject.toml", "rb") as f:
        data = tomllib.load(f)
    assert "redis>=5" in data["project"]["dependencies"]
    assert "hiredis" in data["project"]["dependencies"]
    assert "fakeredis" in data["dependency-groups"]["dev"]


def test_inject_deps_idempotent(tmp_path):
    """Calling inject_deps twice must not duplicate entries."""
    _write_pyproject(tmp_path, _minimal_pyproject())
    inject_deps(tmp_path, ["redis>=5"], ["fakeredis"])
    inject_deps(tmp_path, ["redis>=5"], ["fakeredis"])
    text = (tmp_path / "pyproject.toml").read_text()
    assert text.count("redis>=5") == 1
    assert text.count("fakeredis") == 1


def test_inject_deps_empty_lists_noop(tmp_path):
    original = _minimal_pyproject(deps=["python-dotenv", "fastapi"])
    _write_pyproject(tmp_path, original)
    added, added_dev = inject_deps(tmp_path, [], [])
    assert added == []
    assert added_dev == []
    text = (tmp_path / "pyproject.toml").read_text()
    assert "fastapi" in text


def test_inject_deps_multiple_calls_accumulate(tmp_path):
    _write_pyproject(tmp_path, _minimal_pyproject())
    inject_deps(tmp_path, ["redis>=5"], [])
    inject_deps(tmp_path, ["hiredis"], [])
    text = (tmp_path / "pyproject.toml").read_text()
    assert "redis>=5" in text
    assert "hiredis" in text


# ── inject_deps — name normalisation ─────────────────────────────────────────


def test_inject_deps_same_package_not_duplicated(tmp_path):
    _write_pyproject(
        tmp_path, _minimal_pyproject(deps=["python-dotenv", "python-dotenv"])
    )
    added, _ = inject_deps(tmp_path, ["python-dotenv"], [])
    assert added == []


def test_inject_deps_dep_with_version_not_duplicated_when_bare_present(tmp_path):
    # "redis" already present bare — "redis>=5" skipped (same pkg name)
    _write_pyproject(tmp_path, _minimal_pyproject(deps=["python-dotenv", "redis"]))
    added, _ = inject_deps(tmp_path, ["redis>=5"], [])
    assert added == []
