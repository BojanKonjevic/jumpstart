"""Tests for zenit.generate — recipe rendering and deduplication."""

from pathlib import Path
from unittest.mock import MagicMock

from zenit.core._paths import get_zenit_root
from zenit.core.filesystem import FileSystem
from zenit.core.generate import generate_all
from zenit.core.recipes import _recipe_name
from zenit.schema.models import Contributions

# ── _recipe_name ──────────────────────────────────────────────────────────────


def test_recipe_name_simple():
    assert _recipe_name("test:\n    uv run pytest") == "test"


def test_recipe_name_with_comment():
    assert _recipe_name("# run tests\ntest:\n    uv run pytest") == "test"


def test_recipe_name_with_args():
    assert _recipe_name('migrate msg="":\n    uv run alembic') == "migrate"


def test_recipe_name_with_deps():
    assert (
        _recipe_name("upgrade: wait-db\n    uv run alembic upgrade head") == "upgrade"
    )


def test_recipe_name_strips_whitespace():
    assert _recipe_name("  test  :\n    uv run pytest") == "test"


def test_recipe_name_with_leading_comment_and_args():
    assert (
        _recipe_name('# generate migration\nmigrate msg="":\n    uv run alembic')
        == "migrate"
    )


def test_recipe_name_comment_only():
    assert _recipe_name("# just a comment\n# another comment") is None


def test_recipe_name_empty_string():
    assert _recipe_name("") is None


def test_recipe_name_whitespace_only():
    assert _recipe_name("   \n  ") is None


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_contributions(addon_recipes: list[str]) -> Contributions:
    c = Contributions()
    c.recipes.addon = addon_recipes
    return c


def _make_ctx(tmp_path: Path) -> MagicMock:
    ctx = MagicMock()
    ctx.name = "myproject"
    ctx.pkg_name = "myproject"
    ctx.template = "blank"
    ctx.addons = []
    ctx.dry_run = False
    ctx.zenit_root = get_zenit_root()
    ctx.project_dir = tmp_path
    return ctx


def _make_fs() -> MagicMock:
    fs = MagicMock(spec=FileSystem)
    written: dict[str, str] = {}
    fs._written = written

    def write_file(path: str, content: str) -> None:
        written[path] = content

    fs.write_file.side_effect = write_file
    return fs


def _get_justfile(fs: MagicMock) -> str:
    return fs._written.get("justfile", "")


# ── generate_all ──────────────────────────────────────────────────────────────


def test_generate_all_includes_template_recipes(tmp_path):
    ctx = _make_ctx(tmp_path)
    fs = _make_fs()
    contributions = _make_contributions([])
    contributions.recipes.template = ["# run the app\nrun:\n    python -m myproject"]

    generate_all(ctx, fs, contributions)

    justfile = _get_justfile(fs)
    assert "run:" in justfile
    assert "# run the app" in justfile


def test_generate_all_includes_addon_recipes(tmp_path):
    ctx = _make_ctx(tmp_path)
    fs = _make_fs()
    contributions = _make_contributions(
        ["# start redis\nredis-up:\n    docker compose up -d redis"]
    )

    generate_all(ctx, fs, contributions)

    justfile = _get_justfile(fs)
    assert "redis-up:" in justfile
    assert "# start redis" in justfile


def test_generate_all_deduplicates_by_recipe_name(tmp_path):
    ctx = _make_ctx(tmp_path)
    fs = _make_fs()
    # Both template and addon define "run" — the addon's version should be dropped.
    contributions = _make_contributions(
        ["# start server\nrun:\n    uvicorn myproject.main:app"]
    )
    contributions.recipes.template = ["# run the app\nrun:\n    python -m myproject"]

    generate_all(ctx, fs, contributions)

    justfile = _get_justfile(fs)
    assert justfile.count("run:") == 1
    assert "python -m myproject" in justfile
    assert "uvicorn" not in justfile


def test_generate_all_keeps_distinct_addon_recipes(tmp_path):
    ctx = _make_ctx(tmp_path)
    fs = _make_fs()
    contributions = _make_contributions(
        [
            "# start redis\nredis-up:\n    docker compose up -d redis",
            "# stop redis\nredis-down:\n    docker compose stop redis",
        ]
    )
    contributions.recipes.template = ["# run the app\nrun:\n    python -m myproject"]

    generate_all(ctx, fs, contributions)

    justfile = _get_justfile(fs)
    assert "redis-up:" in justfile
    assert "redis-down:" in justfile


def test_generate_all_renders_pkg_name_in_recipes(tmp_path):
    ctx = _make_ctx(tmp_path)
    fs = _make_fs()
    contributions = _make_contributions([])
    contributions.recipes.template = [
        "# run the app\nrun:\n    uv run uvicorn (( pkg_name )).main:app --reload"
    ]

    generate_all(ctx, fs, contributions)

    justfile = _get_justfile(fs)
    assert "myproject.main:app" in justfile
    assert "(( pkg_name ))" not in justfile


def test_generate_all_renders_name_in_recipes(tmp_path):
    ctx = _make_ctx(tmp_path)
    fs = _make_fs()
    contributions = _make_contributions([])
    contributions.recipes.template = [
        "# create db\ndb-create:\n    docker compose exec db createdb -U postgres (( name ))"
    ]

    generate_all(ctx, fs, contributions)

    justfile = _get_justfile(fs)
    assert "createdb -U postgres myproject" in justfile
    assert "(( name ))" not in justfile


def test_generate_all_writes_pyproject_toml(tmp_path):
    ctx = _make_ctx(tmp_path)
    fs = _make_fs()
    contributions = _make_contributions([])
    contributions.deps = ["fastapi", "uvicorn[standard]", "redis>=5"]

    generate_all(ctx, fs, contributions)

    pyproject = fs._written.get("pyproject.toml", "")
    assert "myproject" in pyproject
    assert "fastapi" in pyproject
    assert "uvicorn[standard]" in pyproject
    assert "redis>=5" in pyproject
