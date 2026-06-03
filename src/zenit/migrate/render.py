"""File content rendering, diagnostics, and unresolved-marker scanning."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import jinja2
import jinja2.meta

from .env import COPIER_ENV

_KNOWN_JINJA2_TAGS: set[str] = {
    "if",
    "elif",
    "else",
    "endif",
    "for",
    "endfor",
    "set",
    "endset",
    "block",
    "endblock",
    "extends",
    "include",
    "import",
    "from",
    "macro",
    "endmacro",
    "call",
    "endcall",
    "filter",
    "endfilter",
    "raw",
    "endraw",
    "autoescape",
    "endautoescape",
    "do",
    "break",
    "continue",
    "with",
    "endwith",
    "namespace",
    "endnamespace",
}


def _diagnose_failed_render(
    content: str,
    question_names: set[str],
    render_env: jinja2.Environment,
) -> str:
    issues: list[str] = []

    try:
        ast = render_env.parse(content)
        undeclared = jinja2.meta.find_undeclared_variables(ast)
        env_known: set[str] = set(render_env.globals.keys()) | set(
            render_env.filters.keys()
        )
        unknown = undeclared - question_names - env_known
        if unknown:
            issues.append(
                f"unknown variables: {', '.join(sorted(unknown))} "
                f"(provide with -D <name>=<value>)"
            )
    except Exception as e:
        issues.append(f"parse error: {e}")

    found_tags = set(re.findall(r"{%[-\s]*(\w+)", content))
    unknown_tags = found_tags - _KNOWN_JINJA2_TAGS
    if unknown_tags:
        issues.append(f"unknown tags: {', '.join(sorted(unknown_tags))}")

    if not issues:
        issues.append("complex Jinja2 pattern — not fully supported")

    return "; ".join(issues)


def _render_file_content(
    content: str,
    render_env: jinja2.Environment | None,
    render_vars: dict[str, Any],
    question_names: set[str],
) -> tuple[str | None, str | None]:
    passes: list[tuple[str, jinja2.Environment]] = []
    if render_env is not None:
        passes.append(("extended", render_env))
    passes.append(("standard", COPIER_ENV))

    last_rendered: str | None = None
    last_env: jinja2.Environment = COPIER_ENV
    first_error: Exception | None = None
    for _pass_name, env in passes:
        last_env = env
        try:
            rendered = env.from_string(content).render(**render_vars)
            last_rendered = rendered
        except Exception as e:
            if first_error is None:
                first_error = e
            continue

        if "{{" not in rendered and "{%" not in rendered:
            return rendered, None

        diagnostic = _diagnose_failed_render(content, question_names, env)
        return rendered, diagnostic

    if last_rendered is not None:
        diagnostic = _diagnose_failed_render(content, question_names, last_env)
        return last_rendered, diagnostic

    diagnostic = _diagnose_failed_render(content, question_names, last_env)
    if first_error is not None:
        msg = str(first_error)
        truncated = msg[:200] + "..." if len(msg) > 200 else msg
        diagnostic = f"rendering error: {truncated}"
    return None, diagnostic


def _scan_for_unresolved_markers(
    project_dir: Path,
    rendered_file_paths: set[str],
) -> list[str]:
    flagged: list[str] = []
    for rel_path in rendered_file_paths:
        if "/charts/" in rel_path or rel_path.startswith("charts/"):
            continue
        full = project_dir / rel_path
        if not full.exists():
            continue
        try:
            content = full.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        no_gha = re.sub(r"\$\{\{.*?\}\}", "", content)
        if "{{" in no_gha or "{%" in no_gha or "{#" in no_gha:
            flagged.append(rel_path)
    return flagged
