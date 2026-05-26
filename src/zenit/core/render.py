"""Central Jinja2 environment factory and render-variables builder.

All templates and addons use ``make_env()`` so the custom delimiters stay
defined in exactly one place.

Custom delimiters
-----------------
Variable:  ``(( … ))``   instead of ``{{ … }}``
Block:     ``[% … %]``   instead of ``{% … %}``
Comment:   disabled      (``line_comment_prefix=None``)

The non-standard delimiters let Jinja2 templates coexist with Python source
files and YAML that use ``{{}}`` and ``{%%}`` as literal text (e.g. Docker
Compose files, Alembic scripts).

trim_blocks / lstrip_blocks
---------------------------
Both are enabled so that ``[% if … %]`` / ``[% endif %]`` block tags do not
leave behind blank lines in the rendered output when their body is empty or
omitted. Without these options, a conditional block that evaluates to nothing
still contributes a newline for the tag line itself.
"""

from __future__ import annotations

from pathlib import Path

import jinja2


def make_env(loader_path: Path | None = None) -> jinja2.Environment:
    """Return a Jinja2 Environment with zenit's custom delimiters.

    Parameters
    ----------
    loader_path:
        Directory to use as the template search path.  Pass ``None`` (or omit)
        when rendering strings directly via ``env.from_string()``.
    """
    loader: jinja2.BaseLoader
    if loader_path is not None:
        loader = jinja2.FileSystemLoader(str(loader_path))
    else:
        loader = jinja2.BaseLoader()

    return jinja2.Environment(
        loader=loader,
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
        variable_start_string="((",
        variable_end_string="))",
        block_start_string="[%",
        block_end_string="%]",
        # Explicitly disable the default "##" line-comment prefix so that
        # double-hash comments in generated Python files are never stripped.
        line_comment_prefix=None,
    )


def build_render_vars(
    name: str,
    pkg_name: str,
    template: str,
    *,
    secret_key: str = "change-me-run-openssl-rand-hex-32",
    addons: list[str] | None = None,
    deps: list[str] | None = None,
    dev_deps: list[str] | None = None,
    python_version: str = "3.12",
) -> dict[str, object]:
    """Build the standard render-variables dict for template rendering.

    ``addon_ids`` provides a set of all addon IDs for quick membership checks;
    use ``"postgres" in addon_ids`` / ``"redis" in addon_ids`` to check for
    specific addons.

    ``deps`` and ``dev_deps`` let template files use ``(( deps ))`` and
    ``(( dev_deps ))`` in their content — e.g. to list dependencies in a
    README or generate an ``__init__.py`` that re-exports them.

    ``python_version`` should be ``"major.minor"`` (e.g. ``"3.14"``).
    Defaults to ``"3.12"`` as a safe fallback.
    """
    addon_list = addons or []
    addon_ids = set(addon_list)
    return {
        "name": name,
        "pkg_name": pkg_name,
        "template": template,
        "secret_key": secret_key,
        "addons": addon_list,
        "addon_ids": addon_ids,
        "deps": deps or [],
        "dev_deps": dev_deps or [],
        "python_version": python_version,
    }


def build_recipe_render_vars(
    name: str,
    pkg_name: str,
    template: str,
    addons: list[str],
    deps: list[str] | None = None,
    dev_deps: list[str] | None = None,
    python_version: str = "3.12",
) -> dict[str, object]:
    """Build render-variables for Justfile recipe rendering only."""
    return {
        "name": name,
        "pkg_name": pkg_name,
        "template": template,
        "addons": addons,
        "deps": deps or [],
        "dev_deps": dev_deps or [],
        "python_version": python_version,
    }
