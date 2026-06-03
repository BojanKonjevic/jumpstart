"""Stub for the ``copier-templates-extensions`` package."""

from __future__ import annotations

import jinja2
import jinja2.nodes
import jinja2.parser


class ContextHook(jinja2.ext.Extension):
    """Stub for ``copier_templates_extensions.ContextHook``."""

    tags = set()

    def __init__(self, environment: jinja2.Environment) -> None:
        super().__init__(environment)

    def parse(self, parser: jinja2.parser.Parser) -> jinja2.nodes.Node:
        return jinja2.nodes.Output([])

    def hook(self, context: dict[str, object]) -> None:
        pass


class TemplateExtensionLoader(jinja2.ext.Extension):
    """Stub for ``copier_templates_extensions.TemplateExtensionLoader``.

    The real loader adds the template directory to ``sys.path`` and
    discovers extension classes.  ``build_extended_env`` already handles
    this, so this stub is a no-op.
    """

    tags = set()

    def __init__(self, environment: jinja2.Environment) -> None:
        super().__init__(environment)

    def parse(self, parser: jinja2.parser.Parser) -> jinja2.nodes.Node:
        return jinja2.nodes.Output([])
