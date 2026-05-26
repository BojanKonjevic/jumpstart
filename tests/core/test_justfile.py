"""Tests for zenit.justfile — injecting just recipes into existing justfiles.

Covers inject_just_recipes, extract_recipe_name, and _extract_recipe_names for all
relevant cases: adding new recipes, skipping duplicates, preserving formatting,
and edge cases.
"""

from __future__ import annotations

from pathlib import Path

from zenit.core.constants import extract_recipe_name
from zenit.core.justfile import (
    _extract_recipe_names,
    inject_just_recipes,
)

# ── extract_recipe_name ──────────────────────────────────────────────────────


def test_recipe_name_simple():
    assert extract_recipe_name("test:\n    uv run pytest") == "test"


def test_recipe_name_with_comment():
    assert extract_recipe_name("# run tests\ntest:\n    uv run pytest") == "test"


def test_recipe_name_with_multiple_comments():
    assert extract_recipe_name("# comment 1\n# comment 2\ntest:\n    cmd") == "test"


def test_recipe_name_with_args():
    assert extract_recipe_name('migrate msg="":\n    uv run alembic') == "migrate"


def test_recipe_name_with_deps():
    assert extract_recipe_name("upgrade: wait-db\n    cmd") == "upgrade"


def test_recipe_name_strips_whitespace():
    assert extract_recipe_name("  run  :\n    cmd") == "run"


def test_recipe_name_hyphenated():
    assert extract_recipe_name("docker-up:\n    docker compose up") == "docker-up"


def test_recipe_name_with_leading_newline():
    assert extract_recipe_name("\nrun:\n    cmd") == "run"


def test_recipe_name_all_comments_returns_none():
    assert extract_recipe_name("# just a comment\n# another comment") is None


def test_recipe_name_empty_string_returns_none():
    assert extract_recipe_name("") is None


# ── _extract_recipe_names ────────────────────────────────────────────────────


def test_extract_recipe_names_simple():
    text = "test:\n    uv run pytest\n"
    assert "test" in _extract_recipe_names(text)


def test_extract_recipe_names_multiple():
    text = "test:\n    cmd\nlint:\n    ruff check .\nfmt:\n    ruff format .\n"
    names = _extract_recipe_names(text)
    assert "test" in names
    assert "lint" in names
    assert "fmt" in names


def test_extract_recipe_names_ignores_indented_lines():
    text = "test:\n    run:\n        cmd\n"
    names = _extract_recipe_names(text)
    assert "test" in names
    assert "run" not in names


def test_extract_recipe_names_ignores_comment_lines():
    text = "# not a recipe\ntest:\n    cmd\n"
    names = _extract_recipe_names(text)
    assert "test" in names
    assert len([n for n in names if n == "#"]) == 0


def test_extract_recipe_names_ignores_lines_without_colon():
    text = "no colon here\ntest:\n    cmd\n"
    names = _extract_recipe_names(text)
    assert "test" in names
    assert "no colon here" not in names


def test_extract_recipe_names_hyphenated():
    text = "docker-up:\n    docker compose up\n"
    names = _extract_recipe_names(text)
    assert "docker-up" in names


def test_extract_recipe_names_with_args():
    text = 'migrate msg="":\n    uv run alembic\n'
    names = _extract_recipe_names(text)
    assert "migrate" in names


def test_extract_recipe_names_with_deps():
    text = "upgrade: wait-db\n    cmd\n"
    names = _extract_recipe_names(text)
    assert "upgrade" in names


def test_extract_recipe_names_empty_justfile():
    assert _extract_recipe_names("") == set()


def test_extract_recipe_names_set_header():
    text = 'set windows-shell := ["cmd", "/C"]\ntest:\n    pytest\n'
    names = _extract_recipe_names(text)
    assert "test" in names
    assert "set windows-shell" not in names


# ── inject_just_recipes — basic behaviour ────────────────────────────────────


def _write_justfile(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "justfile"
    p.write_text(content, encoding="utf-8")
    return p


def test_inject_adds_new_recipe(tmp_path):
    _write_justfile(tmp_path, "test:\n    uv run pytest\n")
    added = inject_just_recipes(tmp_path, ["redis-up:\n    docker compose up -d redis"])
    assert "redis-up" in added
    text = (tmp_path / "justfile").read_text()
    assert "redis-up:" in text


def test_inject_appends_to_end(tmp_path):
    _write_justfile(tmp_path, "test:\n    uv run pytest\n")
    inject_just_recipes(tmp_path, ["redis-up:\n    docker compose up -d redis"])
    text = (tmp_path / "justfile").read_text()
    assert text.index("test:") < text.index("redis-up:")


def test_inject_skips_existing_recipe(tmp_path):
    _write_justfile(tmp_path, "test:\n    uv run pytest\n")
    added = inject_just_recipes(tmp_path, ["test:\n    something else"])
    assert added == []
    text = (tmp_path / "justfile").read_text()
    assert text.count("test:") == 1
    assert "something else" not in text


def test_inject_multiple_recipes(tmp_path):
    _write_justfile(tmp_path, "test:\n    uv run pytest\n")
    recipes = [
        "redis-up:\n    docker compose up -d redis",
        "redis-down:\n    docker compose stop redis",
    ]
    added = inject_just_recipes(tmp_path, recipes)
    assert "redis-up" in added
    assert "redis-down" in added
    text = (tmp_path / "justfile").read_text()
    assert "redis-up:" in text
    assert "redis-down:" in text


def test_inject_partial_skip(tmp_path):
    _write_justfile(tmp_path, "test:\n    pytest\nredis-up:\n    docker compose up\n")
    added = inject_just_recipes(
        tmp_path,
        [
            "redis-up:\n    docker compose up -d redis",
            "redis-down:\n    docker compose stop redis",
        ],
    )
    assert "redis-up" not in added
    assert "redis-down" in added
    text = (tmp_path / "justfile").read_text()
    assert text.count("redis-up:") == 1


def test_inject_returns_list_of_added_names(tmp_path):
    _write_justfile(tmp_path, "test:\n    pytest\n")
    added = inject_just_recipes(
        tmp_path, ["redis-up:\n    up", "redis-down:\n    down"]
    )
    assert set(added) == {"redis-up", "redis-down"}


def test_inject_returns_empty_when_nothing_added(tmp_path):
    _write_justfile(tmp_path, "test:\n    pytest\n")
    added = inject_just_recipes(tmp_path, ["test:\n    something"])
    assert added == []


def test_inject_preserves_existing_content(tmp_path):
    original = "# my justfile\ntest:\n    uv run pytest -v\nlint:\n    ruff check .\n"
    _write_justfile(tmp_path, original)
    inject_just_recipes(tmp_path, ["redis-up:\n    docker compose up -d redis"])
    text = (tmp_path / "justfile").read_text()
    assert "# my justfile" in text
    assert "uv run pytest -v" in text
    assert "ruff check ." in text


def test_inject_no_justfile_returns_empty(tmp_path):
    added = inject_just_recipes(tmp_path, ["test:\n    pytest"])
    assert added == []


def test_inject_empty_recipe_list(tmp_path):
    original = "test:\n    pytest\n"
    _write_justfile(tmp_path, original)
    added = inject_just_recipes(tmp_path, [])
    assert added == []
    assert (tmp_path / "justfile").read_text() == original


def test_inject_recipe_with_comment(tmp_path):
    _write_justfile(tmp_path, "test:\n    pytest\n")
    added = inject_just_recipes(
        tmp_path, ["# start redis\nredis-up:\n    docker compose up -d redis"]
    )
    assert "redis-up" in added
    text = (tmp_path / "justfile").read_text()
    assert "# start redis" in text
    assert "redis-up:" in text


def test_inject_recipe_with_multiline_body(tmp_path):
    _write_justfile(tmp_path, "test:\n    pytest\n")
    recipe = (
        "db-create:\n    docker compose up -d db\n    just wait-db\n    just upgrade"
    )
    inject_just_recipes(tmp_path, [recipe])
    text = (tmp_path / "justfile").read_text()
    assert "db-create:" in text
    assert "just wait-db" in text
    assert "just upgrade" in text


def test_inject_idempotent(tmp_path):
    _write_justfile(tmp_path, "test:\n    pytest\n")
    recipe = "redis-up:\n    docker compose up -d redis"
    inject_just_recipes(tmp_path, [recipe])
    inject_just_recipes(tmp_path, [recipe])
    text = (tmp_path / "justfile").read_text()
    assert text.count("redis-up:") == 1


def test_inject_hyphenated_recipe_name_not_confused_with_existing(tmp_path):
    _write_justfile(tmp_path, "docker-up:\n    docker compose up\n")
    added = inject_just_recipes(tmp_path, ["docker-down:\n    docker compose down"])
    assert "docker-down" in added
    text = (tmp_path / "justfile").read_text()
    assert "docker-up:" in text
    assert "docker-down:" in text


def test_inject_does_not_corrupt_file_on_empty_justfile(tmp_path):
    _write_justfile(tmp_path, "")
    added = inject_just_recipes(tmp_path, ["test:\n    pytest"])
    assert "test" in added
    text = (tmp_path / "justfile").read_text()
    assert "test:" in text


def test_inject_trailing_newline_preserved(tmp_path):
    _write_justfile(tmp_path, "test:\n    pytest\n")
    inject_just_recipes(tmp_path, ["lint:\n    ruff check ."])
    text = (tmp_path / "justfile").read_text()
    assert text.endswith("\n")


def test_inject_recipe_with_args(tmp_path):
    _write_justfile(tmp_path, "test:\n    pytest\n")
    recipe = 'migrate msg="":\n    uv run alembic revision --autogenerate -m "{{msg}}"'
    added = inject_just_recipes(tmp_path, [recipe])
    assert "migrate" in added
    text = (tmp_path / "justfile").read_text()
    assert "migrate" in text


def test_inject_recipe_with_dependency(tmp_path):
    _write_justfile(tmp_path, "wait-db:\n    python scripts/wait_db.py\n")
    recipe = "upgrade: wait-db\n    uv run alembic upgrade head"
    added = inject_just_recipes(tmp_path, [recipe])
    assert "upgrade" in added
    text = (tmp_path / "justfile").read_text()
    assert "upgrade: wait-db" in text


def test_inject_full_set_of_addon_recipes(tmp_path):
    base = (
        'set windows-shell := ["cmd", "/C"]\n\n'
        "default:\n    @just --list\n\n"
        "test:\n    uv run pytest -v\n"
        "lint:\n    uv run ruff check .\n"
        "fmt:\n    uv run ruff format .\n"
        "fix:\n    uv run ruff check --fix .\n    uv run ruff format .\n"
        "check:\n    uv run mypy src/\n"
        "run:\n    uv run uvicorn myapp.main:app --reload\n"
    )
    _write_justfile(tmp_path, base)
    addon_recipes = [
        "# build and start all services\ndocker-up:\n    docker compose up --build",
        "# stop all services\ndocker-down:\n    docker compose down",
        "# start redis\nredis-up:\n    docker compose up -d redis",
        "# stop redis\nredis-down:\n    docker compose stop redis",
        "# open redis-cli\nredis-cli:\n    redis-cli",
    ]
    added = inject_just_recipes(tmp_path, addon_recipes)
    assert set(added) == {
        "docker-up",
        "docker-down",
        "redis-up",
        "redis-down",
        "redis-cli",
    }
    text = (tmp_path / "justfile").read_text()
    # All original recipes must survive
    for recipe in ["test:", "lint:", "fmt:", "fix:", "check:", "run:"]:
        assert recipe in text
    # All new recipes must be present
    for recipe in [
        "docker-up:",
        "docker-down:",
        "redis-up:",
        "redis-down:",
        "redis-cli:",
    ]:
        assert recipe in text
    # No duplicates
    for name in ["test", "lint", "fmt", "fix", "check", "run"]:
        assert text.count(f"{name}:") == 1
