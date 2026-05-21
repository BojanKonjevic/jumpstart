"""Tests for zenit.generate — recipe rendering and deduplication."""

from pathlib import Path
from unittest.mock import MagicMock

from zenit.core._paths import get_zenit_root
from zenit.core.generate import _recipe_name, generate_all
from zenit.schema.models import Contributions, TemplateConfig

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


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_template_config(recipes: list[str]) -> TemplateConfig:
    return TemplateConfig(
        id="blank",
        description="test",
        just_recipes=recipes,
        deps=[],
        dev_deps=[],
    )


def _make_contributions(recipes: list[str]) -> Contributions:
    c = Contributions()
    c.just_recipes = recipes
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
    written: dict[str, str] = {}
    ctx._written = written

    def write_file(path: str, content: str) -> None:
        written[path] = content

    ctx.write_file.side_effect = write_file
    return ctx


def _get_justfile(ctx: MagicMock) -> str:
    return ctx._written.get("justfile", "")


# ── generate_all ──────────────────────────────────────────────────────────────


def test_generate_all_includes_template_recipes(tmp_path):
    ctx = _make_ctx(tmp_path)
    template_cfg = _make_template_config(
        ["# run the app\nrun:\n    python -m myproject"]
    )
    contributions = _make_contributions([])

    generate_all(ctx, template_cfg, contributions)

    justfile = _get_justfile(ctx)
    assert "run:" in justfile
    assert "# run the app" in justfile


def test_generate_all_includes_addon_recipes(tmp_path):
    ctx = _make_ctx(tmp_path)
    template_cfg = _make_template_config([])
    contributions = _make_contributions(
        ["# start redis\nredis-up:\n    docker compose up -d redis"]
    )

    generate_all(ctx, template_cfg, contributions)

    justfile = _get_justfile(ctx)
    assert "redis-up:" in justfile
    assert "# start redis" in justfile


def test_generate_all_deduplicates_by_recipe_name(tmp_path):
    ctx = _make_ctx(tmp_path)
    # Both template and addon define "run" — the addon's version should be dropped.
    template_cfg = _make_template_config(
        ["# run the app\nrun:\n    python -m myproject"]
    )
    contributions = _make_contributions(
        ["# start server\nrun:\n    uvicorn myproject.main:app"]
    )

    generate_all(ctx, template_cfg, contributions)

    justfile = _get_justfile(ctx)
    assert justfile.count("run:") == 1
    assert "python -m myproject" in justfile
    assert "uvicorn" not in justfile


def test_generate_all_keeps_distinct_addon_recipes(tmp_path):
    ctx = _make_ctx(tmp_path)
    template_cfg = _make_template_config(
        ["# run the app\nrun:\n    python -m myproject"]
    )
    contributions = _make_contributions(
        [
            "# start redis\nredis-up:\n    docker compose up -d redis",
            "# stop redis\nredis-down:\n    docker compose stop redis",
        ]
    )

    generate_all(ctx, template_cfg, contributions)

    justfile = _get_justfile(ctx)
    assert "redis-up:" in justfile
    assert "redis-down:" in justfile


def test_generate_all_renders_pkg_name_in_recipes(tmp_path):
    ctx = _make_ctx(tmp_path)
    template_cfg = _make_template_config(
        ["# run the app\nrun:\n    uv run uvicorn (( pkg_name )).main:app --reload"]
    )
    contributions = _make_contributions([])

    generate_all(ctx, template_cfg, contributions)

    justfile = _get_justfile(ctx)
    assert "myproject.main:app" in justfile
    assert "(( pkg_name ))" not in justfile


def test_generate_all_renders_name_in_recipes(tmp_path):
    ctx = _make_ctx(tmp_path)
    template_cfg = _make_template_config(
        [
            "# create db\ndb-create:\n    docker compose exec db createdb -U postgres (( name ))"
        ]
    )
    contributions = _make_contributions([])

    generate_all(ctx, template_cfg, contributions)

    justfile = _get_justfile(ctx)
    assert "createdb -U postgres myproject" in justfile
    assert "(( name ))" not in justfile


def test_generate_all_writes_pyproject_toml(tmp_path):
    ctx = _make_ctx(tmp_path)
    template_cfg = _make_template_config([])
    template_cfg.deps = ["fastapi", "uvicorn[standard]"]
    contributions = _make_contributions([])
    contributions.deps = ["fastapi", "uvicorn[standard]", "redis>=5"]

    generate_all(ctx, template_cfg, contributions)

    pyproject = ctx._written.get("pyproject.toml", "")
    assert "myproject" in pyproject
    assert "fastapi" in pyproject
    assert "uvicorn[standard]" in pyproject
    assert "redis>=5" in pyproject
