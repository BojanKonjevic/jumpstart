"""Generate ``pyproject.toml`` and ``justfile`` from template + addon contributions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from zenit.cli.ui import step, success
from zenit.core.filesystem import FileSystem
from zenit.core.recipes import _recipe_name
from zenit.core.render import build_recipe_render_vars, make_env

if TYPE_CHECKING:
    from zenit.core.context import Context
    from zenit.schema.models import Contributions


def generate_all(
    ctx: Context,
    fs: FileSystem,
    contributions: Contributions,
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
    )

    rendered_template_recipes = [
        string_env.from_string(raw).render(**render_vars)
        for raw in contributions.recipes.template
    ]

    rendered_addon_recipes = [
        string_env.from_string(raw).render(**render_vars)
        for raw in contributions.recipes.addon
    ]

    # Drop addon recipes whose name already appears in the template set so
    # that addon authors can override a template recipe without duplication.
    template_recipe_names = {
        n
        for r in rendered_template_recipes
        if r.strip()
        for n in (_recipe_name(r),)
        if n is not None
    }
    unique_addon_recipes = [
        r
        for r in rendered_addon_recipes
        if r.strip() and _recipe_name(r) not in template_recipe_names
    ]

    template_vars = {
        "name": ctx.name,
        "pkg_name": ctx.pkg_name,
        "template": ctx.template,
        "addons": ctx.addons,
        "deps": contributions.deps,
        "dev_deps": contributions.template_dev_deps + contributions.dev_deps,
        "template_just_recipes": rendered_template_recipes,
        "extra_just_recipes": unique_addon_recipes,
    }

    for template_name, dest_rel in [
        ("pyproject.toml.j2", "pyproject.toml"),
        ("justfile.j2", "justfile"),
    ]:
        content = env.get_template(template_name).render(**template_vars)
        fs.write_file(dest_rel, content)
        if not ctx.dry_run:
            success(dest_rel)
