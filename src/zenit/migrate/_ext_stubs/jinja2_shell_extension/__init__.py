"""Stub for the ``jinja2-shell-extension`` package.

Provides a no-op ``ShellExtension`` that satisfies templates
referencing it; the ``shell()`` filter is already registered
as a safe stub by ``_safe_shell_filter``.
"""

from __future__ import annotations

import jinja2
import jinja2.nodes
import jinja2.parser


class ShellExtension(jinja2.ext.Extension):
    """Stub for ``jinja2_shell_extension.ShellExtension``.

    The ``shell()`` filter is already provided via ``_safe_shell_filter``
    on both ``COPIER_ENV`` and ``render_env``, so this extension class is a
    no-op.
    """

    tags = set()

    def parse(self, parser: jinja2.parser.Parser) -> jinja2.nodes.Node:
        return jinja2.nodes.Output([])
