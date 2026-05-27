"""Generate ``pyproject.toml`` and ``justfile`` from template + addon contributions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from zenit.cli.ui import step, success
from zenit.core._filenames import JUSTFILE_NAME, PYPROJECT_FILE
from zenit.core.filesystem import FileSystem
from zenit.core.render import build_recipe_render_vars, make_env

if TYPE_CHECKING:
    from zenit.core.context import Context
    from zenit.schema.models import Contributions


_GENERATE_FILES: list[tuple[str, str]] = [
    ("pyproject.toml.j2", PYPROJECT_FILE),
    ("justfile.j2", JUSTFILE_NAME),
]


def generate_all(
    ctx: Context,
    fs: FileSystem,
    contributions: Contributions,
    python_version: str = "3.12",
) -> None:
    """Render ``pyproject.toml`` and ``justfile`` and write them to the project."""
    step("Generating config files")
    env = make_env(ctx.zenit_root / "generate")
    string_env = make_env()

    render_vars = build_recipe_render_vars(
        name=ctx.name,
        pkg_name=ctx.pkg_name,
        template=ctx.template,
        addons=ctx.addons,
        deps=contributions.deps,
        dev_deps=contributions.template_dev_deps + contributions.dev_deps,
        python_version=python_version,
    )

    rendered_template_recipes = [
        string_env.from_string(raw).render(**render_vars)
        for raw in contributions.recipes.template
    ]

    # Use RecipeCollection.resolve() to dedup addon recipes by name against templates
    combined = contributions.recipes.resolve()
    unique_addon_raw = combined[len(contributions.recipes.template) :]
    rendered_addon_recipes = [
        string_env.from_string(raw).render(**render_vars) for raw in unique_addon_raw
    ]

    template_vars = {
        "name": ctx.name,
        "pkg_name": ctx.pkg_name,
        "template": ctx.template,
        "addons": ctx.addons,
        "deps": contributions.deps,
        "dev_deps": contributions.template_dev_deps + contributions.dev_deps,
        "template_just_recipes": rendered_template_recipes,
        "extra_just_recipes": rendered_addon_recipes,
        "tool_overrides": contributions.tool_overrides,
        "ruff_excludes": contributions.ruff_excludes,
        "python_version": python_version,
    }

    for template_name, dest_rel in _GENERATE_FILES:
        content = env.get_template(template_name).render(**template_vars)
        fs.write_file(dest_rel, content)
        if not ctx.dry_run:
            success(dest_rel)
