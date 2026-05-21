"""Central Jinja2 environment factory.

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
----------------------------
Both are enabled so that ``[% if … %]`` / ``[% endif %]`` block tags do not
leave behind blank lines in the rendered output when their body is empty or
omitted. Without these options, a conditional block that evaluates to nothing
still contributes a newline for the tag line itself.
"""

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
