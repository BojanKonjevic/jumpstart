"""File operations: template walking, destination rendering, safe task file ops."""

from __future__ import annotations

import fnmatch
import shlex
from pathlib import Path
from typing import Any

import jinja2
import jinja2.meta

from zenit.cli.ui import warn
from zenit.schema.exceptions import ZenitError
from zenit.schema.models import FileContribution

from .copier import (
    CopierConfig,
    CopierTask,
    FileJinjaClass,
    classify_file,
    parse_copier_yml,
)
from .env import COPIER_ENV
from .tasks import _task_command, _task_enabled


def _render_template(
    template_dir: Path,
) -> list[FileContribution]:
    copier_yml = _find_copier_file(template_dir)
    config = parse_copier_yml(copier_yml)
    content_dir = _resolve_content_dir(template_dir, config)

    file_contributions: list[FileContribution] = []

    copier_basename = copier_yml.name
    for f in sorted(content_dir.rglob("*")):
        if not f.is_file() or f.name == copier_basename:
            continue
        if f.parent.name == ".git" or f.name == ".git":
            continue

        rel = f.relative_to(content_dir)
        dest = _destination_template(rel, config.templates_suffix)

        jclass = classify_file(f, config, content_dir, template_dir)

        fc = _build_file_contribution(f, dest, jclass, config)
        if fc is not None:
            file_contributions.append(fc)

    return file_contributions


def _find_copier_file(template_dir: Path) -> Path:
    for name in ("copier.yml", "copier.yaml"):
        candidate = template_dir / name
        if candidate.exists():
            return candidate
    raise ZenitError("No copier.yml or copier.yaml found in '{template_dir}'.")


def _resolve_content_dir(template_dir: Path, config: CopierConfig) -> Path:
    if config.subdirectory:
        sub = template_dir / config.subdirectory
        if not sub.exists():
            raise ZenitError(
                f"Template specifies _subdirectory '{config.subdirectory}' "
                f"but it does not exist in '{template_dir}'."
            )
        return sub
    return template_dir


def _destination_template(rel_path: Path, templates_suffix: str | None = None) -> str:
    dest = str(rel_path)
    if templates_suffix is not None:
        if dest.endswith(templates_suffix):
            return dest[: -len(templates_suffix)]
        return dest
    if dest.endswith(".jinja2"):
        return dest[: -len(".jinja2")]
    if dest.endswith(".jinja"):
        return dest[: -len(".jinja")]
    if dest.endswith(".j2"):
        return dest[: -len(".j2")]
    return dest


def _render_destination_path(
    dest_template: str, render_vars: dict[str, Any]
) -> Path | None:
    try:
        rendered = COPIER_ENV.from_string(dest_template).render(**render_vars).strip()
    except Exception:
        return None
    if not rendered:
        return None
    if rendered.endswith("/"):
        return None
    dest_path = Path(rendered)
    if dest_path.is_absolute() or ".." in dest_path.parts:
        return None
    return dest_path


def _uses_copier_internal_path_vars(dest_template: str) -> bool:
    try:
        referenced = COPIER_ENV.parse(dest_template)
    except Exception:
        return False

    try:
        undeclared = jinja2.meta.find_undeclared_variables(referenced)
    except Exception:
        return False

    return any(name.startswith("_copier_") for name in undeclared)


def _build_file_contribution(
    f: Path,
    dest: str,
    jclass: FileJinjaClass,
    config: CopierConfig,
) -> FileContribution | None:
    if jclass == FileJinjaClass.EXCLUDED:
        return None

    if jclass == FileJinjaClass.STATIC:
        try:
            content = f.read_bytes()
            try:
                text = content.decode("utf-8")
                return FileContribution(dest=dest, content=text, template=False)
            except UnicodeDecodeError:
                return FileContribution(dest=dest, source=str(f), template=False)
        except Exception:
            return FileContribution(dest=dest, source=str(f), template=False)

    if jclass == FileJinjaClass.JINJA2_TEMPLATE:
        try:
            text_content = f.read_text(encoding="utf-8")
            return FileContribution(dest=dest, content=text_content, template=True)
        except Exception:
            warn(f"Failed to read '{dest}' — copied verbatim.")
            return FileContribution(dest=dest, source=str(f), template=False)

    return FileContribution(dest=dest, source=str(f), template=False)


def _apply_safe_task_file_ops(
    contributions: list[FileContribution],
    tasks: list[CopierTask],
    render_vars: dict[str, Any],
    project_dir: Path | None = None,
) -> tuple[list[FileContribution], list[CopierTask]]:
    remaining_tasks: list[CopierTask] = []
    updated = list(contributions)

    for task in tasks:
        if not _task_enabled(task, render_vars):
            continue

        command = _task_command(task)
        if command is None:
            remaining_tasks.append(task)
            continue

        try:
            parts = shlex.split(command)
        except ValueError:
            remaining_tasks.append(task)
            continue

        if len(parts) == 3 and parts[0] == "mv":
            updated = _rewrite_contribution_prefixes(updated, parts[1], parts[2])
            continue
        if len(parts) >= 3 and parts[0] == "rm" and parts[1] in ("-f", "-rf", "-fr"):
            updated = _remove_contribution_targets(updated, parts[2:])
            continue
        if len(parts) == 3 and parts[0] == "mkdir" and parts[1] == "-p":
            target = project_dir / parts[2] if project_dir else Path(parts[2])
            target.mkdir(parents=True, exist_ok=True)
            continue

        remaining_tasks.append(task)

    return updated, remaining_tasks


def _apply_skip_if_exists(
    contributions: list[FileContribution],
    patterns: list[str],
    project_dir: Path,
    render_vars: dict[str, Any],
) -> list[FileContribution]:
    if not patterns:
        return contributions

    filtered: list[FileContribution] = []
    for fc in contributions:
        rendered_dest = _render_destination_path(fc.dest, render_vars)
        if rendered_dest is None:
            continue
        dest_path = project_dir / rendered_dest
        if dest_path.exists() and _matches_any_skip_pattern(
            str(rendered_dest), patterns
        ):
            warn(
                f"Skipping '{rendered_dest}' — _skip_if_exists pattern matched "
                f"and file already exists."
            )
            continue
        filtered.append(fc)
    return filtered


def _rewrite_contribution_prefixes(
    contributions: list[FileContribution],
    source: str,
    dest: str,
) -> list[FileContribution]:
    source_prefix = source.rstrip("/")
    dest_prefix = dest.rstrip("/")
    rewritten: list[FileContribution] = []

    for contribution in contributions:
        current = contribution.dest.replace("\\", "/")
        if current == source_prefix:
            current = dest_prefix
        elif current.startswith(f"{source_prefix}/"):
            current = f"{dest_prefix}/{current[len(source_prefix) + 1 :]}"
        rewritten.append(
            FileContribution(
                dest=current,
                source=contribution.source,
                content=contribution.content,
                template=contribution.template,
            )
        )

    return rewritten


def _remove_contribution_targets(
    contributions: list[FileContribution],
    targets: list[str],
) -> list[FileContribution]:
    normalized = [target.rstrip("/").replace("\\", "/") for target in targets]
    kept: list[FileContribution] = []

    for contribution in contributions:
        norm_dest = contribution.dest.replace("\\", "/")
        if any(
            norm_dest == target or norm_dest.startswith(f"{target}/")
            for target in normalized
        ):
            continue
        kept.append(contribution)

    return kept


def _matches_any_skip_pattern(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, p) for p in patterns)
