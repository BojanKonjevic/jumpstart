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
from pathlib import Path
from typing import TYPE_CHECKING

from zenit.schema.exceptions import ZenitError

if TYPE_CHECKING:
    from zenit.schema.models import ComposeService


def normalise_pkg_name(project_name: str) -> str:
    name = project_name.lower()
    name = re.sub(r"[^a-z0-9_]", "_", name)
    name = name.strip("_")
    if not name:
        raise ZenitError(
            f"Project name '{project_name}' normalised to an empty string. "
            f"Use at least one letter, digit, or underscore."
        )
    return name


def _validate_no_path_traversal(dest: str, project_dir: Path) -> None:
    """Check that *dest* (a path relative to *project_dir*) does not escape.

    Raises
    ------
    ZenitError
        If *dest* resolves to a location outside *project_dir*.
    """
    resolved_dest = (project_dir / dest).resolve()
    resolved_project = project_dir.resolve()
    try:
        resolved_dest.relative_to(resolved_project)
    except ValueError:
        raise ZenitError(
            f"Path traversal detected: '{dest}' resolves to '{resolved_dest}', "
            f"which is outside the project directory '{resolved_project}'. "
            f"This is a security issue in the template or addon — please report it."
        ) from None


def resolve_compose_placeholders(services: list[ComposeService], pkg_name: str) -> None:
    """Resolve ``{{pkg_name}}`` placeholders in compose service fields in-place."""
    for svc in services:
        if svc.command and "{{pkg_name}}" in svc.command:
            svc.command = resolve_dest_placeholder(svc.command, pkg_name)
        if svc.environment:
            svc.environment = {
                k: resolve_dest_placeholder(v, pkg_name) if isinstance(v, str) else v
                for k, v in svc.environment.items()
            }
        if svc.develop_watch:
            for watch in svc.develop_watch:
                if "path" in watch and isinstance(watch["path"], str):
                    watch["path"] = resolve_dest_placeholder(watch["path"], pkg_name)


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
