"""Package name normalisation and ``{{pkg_name}}`` placeholder resolution.

Paths in templates and addons use ``{{pkg_name}}`` (Jinja2-style double-braces)
as the sole supported placeholder.  This is **intentionally** a plain string
substitution, NOT Jinja2 rendering — because zenit's custom Jinja2 delimiters
are ``(( … ))`` and ``[% … %]`` (see :func:`zenit.core.render.make_env`),
so ``{{anything}}`` passes through templates as literal text.

File *content* uses ``(( pkg_name ))`` via Jinja2.  The path layer uses
``{{pkg_name}}`` via :func:`resolve_dest_placeholder`.  The two syntaxes
deliberately do not overlap.
"""

from __future__ import annotations

import re

from zenit.schema.exceptions import ZenitError


def normalise_pkg_name(project_name: str) -> str:
    name = project_name.lower()
    name = re.sub(r"[^a-z0-9_]", "_", name)
    return name.strip("_")


def resolve_dest_placeholder(text: str, pkg_name: str) -> str:
    """Replace ``{{pkg_name}}`` and reject any other ``{{…}}`` patterns.

    This is the only supported placeholder syntax for dest-like path strings
    (``FileContribution.dest``, ``Contributions.dirs``, ``InjectionPoint.file``,
    ``ComposeService.command``, etc.).  It is resolved by plain string
    replacement — NOT through Jinja2.

    Raises
    ------
    ZenitError
        If *text* contains ``{{…}}`` around a variable other than ``pkg_name``.
    """
    for m in re.finditer(r"\{\{(.+?)\}\}", text):
        varname = m.group(1).strip()
        if varname != "pkg_name":
            raise ZenitError(
                f"Unsupported placeholder '{{{{{varname}}}}}' in path template: "
                f"'{text}'. Only '{{{{pkg_name}}}}' is allowed in dest paths. "
                f"Use '(( {varname} ))' (Jinja2 custom delimiters) in file content instead."
            )
    return text.replace("{{pkg_name}}", pkg_name)
