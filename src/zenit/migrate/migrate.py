"""Migration pipeline — ``zenit migrate`` command implementation.

This module handles the end-to-end process of converting a Copier template
into a zenit-managed project: fetching the template source, parsing the
``copier.yml``, prompting the user, rendering files with delimiter translation,
generating inline addon stubs for ADDON_CANDIDATE questions, inventory-scannning
the result, and writing the lockfile and manifest.
"""

from __future__ import annotations

import shlex
import shutil
import subprocess
import tempfile
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import jinja2.meta
import yaml

from zenit.cli.ui import (
    BOLD,
    CYAN,
    DIM,
    RESET,
    YELLOW,
    step,
    success,
    warn,
)
from zenit.core._filenames import COMPOSE_FILE, ENV_FILES, PYPROJECT_FILE
from zenit.core.lockfile import MigratedMeta, write_lockfile
from zenit.core.manifest import (
    add_compose_service,
    add_compose_volume,
    add_dependency,
    add_env_entry,
    dep_package_name,
    read_manifest,
    write_manifest,
)
from zenit.core.rollback import scaffold_or_rollback
from zenit.schema.exceptions import ZenitError
from zenit.schema.models import (
    EntrySource,
    FileContribution,
)

from .copier import (
    COPIER_ENV,
    CopierConfig,
    CopierQuestion,
    CopierTask,
    FileJinjaClass,
    QuestionClass,
    QuestionType,
    classify_file,
    classify_questions,
    parse_copier_yml,
)


@dataclass
class MigrationAnswers:
    """User-provided answers to the template questions."""

    render_vars: dict[str, Any] = field(default_factory=dict)


@dataclass
class MigrationResult:
    """Result of a completed migration."""

    project_dir: Path
    template_source: str
    file_paths: list[str] = field(default_factory=list)
    addon_ids: list[str] = field(default_factory=list)
    has_tasks: bool = False
    env_count: int = 0
    compose_service_count: int = 0
    compose_volume_count: int = 0
    dep_count: int = 0


# ── Source fetching ────────────────────────────────────────────────────────────


def _is_github_url(source: str) -> bool:
    return source.startswith("https://github.com/") or source.startswith("gh:")


def _normalise_source(source: str) -> str:
    """Normalise a Copier source reference to a URL."""
    if source.startswith("gh:"):
        repo = source[3:]
        if "/" not in repo:
            repo = f"{repo}/{repo}"
        return f"https://github.com/{repo}"
    # Resolve relative paths to absolute
    path = Path(source)
    if not str(source).startswith("https://") and not str(source).startswith("http://"):
        return str(path.resolve())
    return source


def _derive_project_name_from_source(source: str) -> str | None:
    """Extract a project name from a GitHub URL or local path."""
    name: str | None = None
    if source.startswith("https://github.com/"):
        parts = source.rstrip("/").split("/")
        if parts:
            name = parts[-1]
    elif source.startswith("gh:"):
        parts = source[3:].split("/")
        name = parts[-1] if parts[-1] else None
    elif "://" not in source:
        path = Path(source)
        n = path.name
        if n and n != ".":
            name = n
    if name and name.endswith(".git"):
        name = name[:-4]
    return name


def _pick_project_name(
    project_name_answer: object,
    name_answer: object,
    source: str,
    template_dir: Path,
) -> str:
    """Pick a project name from available sources in priority order."""
    candidates: list[str | None] = [
        str(project_name_answer).strip() if project_name_answer else None,
        str(name_answer).strip() if name_answer else None,
        _derive_project_name_from_source(source),
        template_dir.name,
    ]
    for c in candidates:
        if c and c.strip():
            return c.strip()
    return template_dir.name


def _fetch_source(source: str) -> Path:
    """Fetch a Copier template source and return the local path.

    For GitHub URLs, clones with ``--depth=1`` into a temporary directory.
    For local paths, returns the path directly after validation.
    """
    normalised = _normalise_source(source)

    if normalised.startswith("https://"):
        tmp = tempfile.mkdtemp(prefix="zenit-migrate-")
        try:
            result = subprocess.run(
                ["git", "clone", "--depth=1", normalised, tmp],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                shutil.rmtree(tmp, ignore_errors=True)
                raise ZenitError(f"Failed to clone template from '{normalised}':\n")
            return Path(tmp)
        except FileNotFoundError:
            shutil.rmtree(tmp, ignore_errors=True)
            raise ZenitError(
                f"git is required to clone '{normalised}'. "
                "Install git and try again, or use a local path."
            ) from None

    # Local path
    path = Path(normalised).resolve()
    if not path.exists():
        raise ZenitError(f"Template path '{path}' does not exist.")
    if not path.is_dir():
        raise ZenitError(f"Template path '{path}' is not a directory.")
    return path


# ── User prompting ─────────────────────────────────────────────────────────────


def _prompt_questions(
    config: CopierConfig,
    classes: dict[str, QuestionClass],
) -> MigrationAnswers:
    """Prompt the user for answers to all Copier template questions.

    Uses zenit's existing prompt patterns (simple input prompts, no TUI).

    All question types — including boolean ADDON_CANDIDATE questions — are
    stored as render-time variables. No inline addon stubs are generated in
    Phase 1 (reserved for Phase 3 ``zenit adopt``).
    """
    answers = MigrationAnswers()

    for q in config.questions:
        qclass = classes.get(q.name, QuestionClass.RENDER_VAR)
        default_value = _coerce_question_value(
            q,
            _render_copier_default(q.default, answers.render_vars),
        )

        if q.type == QuestionType.BOOL:
            msg = f"{q.help or q.name}"
            raw = input(f"  {msg} {DIM}[Y/n]{RESET}  ").strip().lower()
            answer = raw in ("", "y", "yes") if raw else bool(default_value)
            answers.render_vars[q.name] = answer
        elif qclass == QuestionClass.CHOICE_VAR:
            choices_str = ", ".join(q.choices)
            msg = f"{q.help or q.name} {DIM}({choices_str}){RESET}"
            raw = input(f"  {msg} [{default_value}]: ").strip()
            if raw and raw in q.choices:
                answers.render_vars[q.name] = raw
            else:
                answers.render_vars[q.name] = default_value
        elif q.type == QuestionType.INT:
            default_str = str(default_value) if default_value != "" else ""
            msg = f"{q.help or q.name}"
            raw = input(f"  {msg} [{default_str}]: ").strip()
            answers.render_vars[q.name] = int(raw) if raw else default_value
        elif q.type == QuestionType.FLOAT:
            default_str = str(default_value) if default_value != "" else ""
            msg = f"{q.help or q.name}"
            raw = input(f"  {msg} [{default_str}]: ").strip()
            answers.render_vars[q.name] = float(raw) if raw else default_value
        else:
            default_str = str(default_value) if default_value != "" else ""
            msg = f"{q.help or q.name}"
            raw = input(f"  {msg} [{default_str}]: ").strip()
            answers.render_vars[q.name] = raw if raw else default_value

    return answers


def _resolve_answers_noninteractive(
    config: CopierConfig,
    overrides: dict[str, str],
) -> MigrationAnswers:
    """Resolve answers from overrides and defaults without interactive prompts.

    Parameters
    ----------
    config:
        Parsed Copier configuration.
    overrides:
        Explicit key=value overrides (e.g. from ``-D`` or ``-n`` flags).

    Returns
    -------
    MigrationAnswers
        Resolved answers.

    Raises
    ------
    ZenitError
        If any question has no default and no override was provided.
    """
    answers = MigrationAnswers()

    for q in config.questions:
        if q.name in overrides:
            raw = overrides[q.name]
            match q.type:
                case QuestionType.BOOL:
                    answers.render_vars[q.name] = raw.lower() in (
                        "y",
                        "yes",
                        "true",
                        "1",
                        "",
                    )
                case QuestionType.INT:
                    answers.render_vars[q.name] = int(raw)
                case QuestionType.FLOAT:
                    answers.render_vars[q.name] = float(raw)
                case _:
                    answers.render_vars[q.name] = raw
        elif q.default is not None:
            answers.render_vars[q.name] = _coerce_question_value(
                q,
                _render_copier_default(q.default, answers.render_vars),
            )
        else:
            raise ZenitError(
                f"Question '{q.name}' has no default and was not provided. "
                f"Pass it with -D {q.name}=<value>"
            )

    return answers


def _render_copier_default(
    value: object,
    render_vars: dict[str, Any],
) -> object:
    """Render a Copier default value against answers resolved so far."""
    if not isinstance(value, str):
        return value
    if "{{" not in value and "{%" not in value and "{#" not in value:
        return value
    return COPIER_ENV.from_string(value).render(**render_vars)


def _coerce_question_value(
    question: CopierQuestion,
    value: object,
) -> object:
    """Coerce a rendered Copier answer/default to the declared question type."""
    if not isinstance(value, str):
        return value

    match question.type:
        case QuestionType.BOOL:
            return value.strip().lower() in ("1", "true", "yes", "y", "on")
        case QuestionType.INT:
            return int(value) if value.strip() else 0
        case QuestionType.FLOAT:
            return float(value) if value.strip() else 0.0
        case _:
            return value


def _addon_id_from_question(question_name: str) -> str:
    """Derive an addon id from a Copier boolean question name.

    Strips common prefixes (``use_``, ``with_``, ``has_``) and appends
    ``-migrated`` to distinguish from native zenit addons.
    """
    name = question_name.lower()
    for prefix in ("use_", "with_", "has_", "enable_"):
        if name.startswith(prefix):
            name = name[len(prefix) :]
            break
    return f"{name}-migrated"


# ── Template rendering ────────────────────────────────────────────────────────


def _render_template(
    template_dir: Path,
) -> list[FileContribution]:
    """Process files in *template_dir*: classify, translate delimiters.

    Returns all file contributions from the template (both static and
    translated Jinja2 files).  Every Copier question — whether ADDON_CANDIDATE,
    PARTIAL_ADDON, or RENDER_VAR — becomes a render-time variable.  No inline
    addon stubs are created in Phase 1: all content is presence-tracked only
    via the ``[migrated]`` lockfile section.
    """
    copier_yml = _find_copier_file(template_dir)
    config = parse_copier_yml(copier_yml)
    content_dir = _resolve_content_dir(template_dir, config)

    file_contributions: list[FileContribution] = []

    copier_basename = copier_yml.name
    for f in sorted(content_dir.rglob("*")):
        if not f.is_file() or f.name == copier_basename:
            continue
        # Skip .git directory, but keep other dotfiles (e.g. .env.jinja)
        if f.parent.name == ".git" or f.name == ".git":
            continue

        rel = f.relative_to(content_dir)
        dest = _destination_template(rel)

        jclass = classify_file(f, config, content_dir)

        fc = _build_file_contribution(f, dest, jclass, config)
        if fc is not None:
            file_contributions.append(fc)

    return file_contributions


def _find_copier_file(template_dir: Path) -> Path:
    """Find the Copier config file (``copier.yml`` or ``copier.yaml``)."""
    for name in ("copier.yml", "copier.yaml"):
        candidate = template_dir / name
        if candidate.exists():
            return candidate
    raise ZenitError(f"No copier.yml or copier.yaml found in '{template_dir}'.")


def _resolve_content_dir(template_dir: Path, config: CopierConfig) -> Path:
    """Resolve the content directory, taking ``_subdirectory`` into account."""
    if config.subdirectory:
        sub = template_dir / config.subdirectory
        if not sub.exists():
            raise ZenitError(
                f"Template specifies _subdirectory '{config.subdirectory}' "
                f"but it does not exist in '{template_dir}'."
            )
        return sub
    return template_dir


def _destination_template(rel_path: Path) -> str:
    """Build the destination path template for a Copier source file."""
    dest = str(rel_path)
    if dest.endswith(".jinja2"):
        return dest[: -len(".jinja2")]
    if dest.endswith(".jinja"):
        return dest[: -len(".jinja")]
    if dest.endswith(".j2"):
        return dest[: -len(".j2")]
    return dest


def _render_destination_path(dest_template: str, render_vars: dict[str, Any]) -> Path:
    """Render a destination path template using Copier's Jinja environment."""
    rendered = COPIER_ENV.from_string(dest_template).render(**render_vars).strip()
    if not rendered:
        raise ZenitError("Migration produced an empty destination path.")
    dest_path = Path(rendered)
    if dest_path.is_absolute() or ".." in dest_path.parts:
        raise ZenitError(
            f"Migration produced an unsafe destination path: '{rendered}'."
        )
    return dest_path


def _uses_copier_internal_path_vars(dest_template: str) -> bool:
    """Return True when a destination path depends on Copier-only variables."""
    try:
        referenced = COPIER_ENV.parse(dest_template)
    except Exception:
        return False

    for name in jinja2.meta.find_undeclared_variables(referenced):
        if name.startswith("_copier_"):
            return True
    return False


def _build_file_contribution(
    f: Path,
    dest: str,
    jclass: FileJinjaClass,
    config: CopierConfig,
) -> FileContribution | None:
    """Build a single ``FileContribution`` from a template file."""
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


def _task_command(task: CopierTask) -> str | None:
    if isinstance(task, str):
        return task
    command = task.get("command")
    if isinstance(command, str):
        return command
    return None


def _task_enabled(task: CopierTask, render_vars: dict[str, Any]) -> bool:
    if isinstance(task, str):
        return True
    when = task.get("when")
    if not isinstance(when, str) or not when.strip():
        return True
    rendered = COPIER_ENV.from_string(when).render(**render_vars).strip().lower()
    return rendered in ("1", "true", "yes", "y", "on")


def _apply_safe_task_file_ops(
    contributions: list[FileContribution],
    tasks: list[CopierTask],
    render_vars: dict[str, Any],
) -> tuple[list[FileContribution], list[CopierTask]]:
    """Apply safe Copier file-layout tasks and return remaining manual tasks."""
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

        remaining_tasks.append(task)

    return updated, remaining_tasks


def _rewrite_contribution_prefixes(
    contributions: list[FileContribution],
    source: str,
    dest: str,
) -> list[FileContribution]:
    """Rewrite contribution destinations for a safe ``mv`` task."""
    source_prefix = source.rstrip("/")
    dest_prefix = dest.rstrip("/")
    rewritten: list[FileContribution] = []

    for contribution in contributions:
        current = contribution.dest
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
    """Drop contributions matched by a safe ``rm -f`` or ``rm -rf`` task."""
    normalized = [target.rstrip("/") for target in targets]
    kept: list[FileContribution] = []

    for contribution in contributions:
        if any(
            contribution.dest == target or contribution.dest.startswith(f"{target}/")
            for target in normalized
        ):
            continue
        kept.append(contribution)

    return kept


# ── Inventory scan ─────────────────────────────────────────────────────────────


def _inventory_env(project_dir: Path) -> list[str]:
    """Scan .env and .env.example for existing environment variable keys."""
    keys: list[str] = []
    for fname in ENV_FILES:
        path = project_dir / fname
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key = line.split("=", 1)[0].strip()
                if key:
                    keys.append(key)
    return keys


def _inventory_compose(project_dir: Path) -> tuple[list[str], list[str]]:
    """Scan compose.yml for service and volume names."""
    compose_path = project_dir / COMPOSE_FILE
    if not compose_path.exists():
        return [], []
    try:
        data: dict[str, Any] = (
            yaml.safe_load(compose_path.read_text(encoding="utf-8")) or {}
        )
    except Exception:
        return [], []

    services = list(data.get("services", {}).keys())
    volumes = list(data.get("volumes", {}).keys())
    return services, volumes


def _inventory_deps(project_dir: Path) -> list[tuple[str, str, bool]]:
    """Scan pyproject.toml for dependency entries.

    Returns ``(package, spec, dev)`` tuples.
    """
    pyproject_path = project_dir / PYPROJECT_FILE
    if not pyproject_path.exists():
        return []
    try:
        with open(pyproject_path, "rb") as f:
            data = tomllib.load(f)
    except Exception:
        return []

    result: list[tuple[str, str, bool]] = []
    project = data.get("project", {})
    deps = project.get("dependencies", [])
    if isinstance(deps, list):
        for dep in deps:
            if isinstance(dep, str):
                pkg = dep_package_name(dep)
                result.append((pkg, dep, False))

    dep_groups = data.get("dependency-groups", {})
    if isinstance(dep_groups, dict):
        dev = dep_groups.get("dev", [])
        if isinstance(dev, list):
            for dep in dev:
                if isinstance(dep, str):
                    pkg = dep_package_name(dep)
                    result.append((pkg, dep, True))

    return result


# ── Task stubs ─────────────────────────────────────────────────────────────────


def _write_task_stub(project_dir: Path, tasks: list[CopierTask]) -> None:
    """Write a task-stub file that lists the pending _tasks."""
    if not tasks:
        return
    stub_path = project_dir / ".zenit-tasks.md"
    lines = [
        "# Manual Tasks (from Copier _tasks)",
        "",
        "This project was migrated from a Copier template that defined",
        "the following tasks. They were not executed automatically.",
        "",
    ]
    for i, task in enumerate(tasks, 1):
        command = _task_command(task)
        if isinstance(task, dict) and isinstance(task.get("when"), str):
            lines.append(f"  {i}. {command}  [when: {task['when']}]")
        else:
            lines.append(f"  {i}. {command or task}")
    lines.append("")
    stub_path.write_text("\n".join(lines), encoding="utf-8")


# ── Migration report ───────────────────────────────────────────────────────────


def _print_migration_report(result: MigrationResult) -> None:
    """Print the migration report to stdout."""
    print()
    success("Migration complete.")
    print()
    print(f"  {BOLD}Template:{RESET}   {CYAN}{result.template_source}{RESET}")
    print(f"  {BOLD}Project:{RESET}    {result.project_dir.name}/")
    print()

    print(f"  {BOLD}Presence-tracked only:{RESET}")
    print(f"    ~ {len(result.file_paths)} files tracked in [migrated].file_paths")
    if result.env_count > 0:
        print(f"    ~ {result.env_count} env var(s) with source=migrated")
    if result.compose_service_count > 0:
        print(
            f"    ~ {result.compose_service_count} compose service(s) with source=migrated"
        )
    if result.compose_volume_count > 0:
        print(
            f"    ~ {result.compose_volume_count} compose volume(s) with source=migrated"
        )
    if result.dep_count > 0:
        print(f"    ~ {result.dep_count} dependencies with source=migrated")
    print()

    if result.has_tasks:
        print(
            f"  {YELLOW}!{RESET}  {BOLD}Manual steps required:{RESET} "
            f"Copier _tasks were not executed."
        )
        print(
            f"      See {CYAN}.zenit-tasks.md{RESET} for the list of commands "
            f"to run manually."
        )
        print()

    print(
        f"  {DIM}Most post-creation lifecycle features (zenit add, zenit remove,{RESET}"
    )
    print(
        f"  {DIM}zenit doctor integrity checks) work fully only for components{RESET}"
    )
    print(f"  {DIM}zenit owns outright. Run 'zenit adopt <addon>' to bring{RESET}")
    print(f"  {DIM}components under full management. Run 'zenit doctor' to see{RESET}")
    print(f"  {DIM}the current health report.{RESET}")
    print()


# ── Main migration function ────────────────────────────────────────────────────


def run_migration(
    source: str,
    *,
    name: str | None = None,
    data: dict[str, str] | None = None,
) -> MigrationResult:
    """Run the full migration pipeline.

    The project directory is created in the current working directory and
    named after the user's ``project_name`` (or ``name``) answer to the
    Copier questions, falling back to the template source directory name.

    Parameters
    ----------
    source:
        Copier template source — a GitHub URL (``https://github.com/user/repo``
        or ``gh:user/repo``) or a local directory path.
    name:
        Project name for non-interactive mode.  Sets ``project_name`` in the
        render variables and skips all interactive prompts.
    data:
        Additional key=value overrides for non-interactive mode (e.g.
        ``{"use_redis": "yes"}``).  Ignored when ``name`` is ``None``.

    Returns
    -------
    MigrationResult
        Summary of the migration for reporting and testing.
    """
    step("Fetching template source")
    template_dir = _fetch_source(source)
    normalised_source = _normalise_source(source)
    template_source = normalised_source

    copier_yml = _find_copier_file(template_dir)
    config = parse_copier_yml(copier_yml)

    step("Analyzing template questions")
    classes = classify_questions(config, template_dir)

    if config.skip_if_exists:
        for pattern in config.skip_if_exists:
            warn(
                f"'_skip_if_exists' pattern '{pattern}' is not supported in migration. "
                f"Any matching files were written unconditionally."
            )

    non_interactive = name is not None or (data is not None and len(data) > 0)

    if non_interactive:
        step("Resolving template answers (non-interactive)")
        overrides: dict[str, str] = {}
        if name is not None:
            overrides["project_name"] = name
        if data is not None:
            overrides.update(data)
        answers = _resolve_answers_noninteractive(config, overrides)
    else:
        step("Prompting for template answers")
        answers = _prompt_questions(config, classes)

    # Derive directory name from the user's project_name answer, or fall back to
    # a name derived from the template source URL/path.
    project_name = _pick_project_name(
        answers.render_vars.get("project_name"),
        answers.render_vars.get("name"),
        normalised_source,
        template_dir,
    )
    answers.render_vars["project_name"] = project_name

    # Re-derive any variable whose default references project_name (e.g.
    # package_name = "{{ project_name | replace('-', '_') }}"). Without this,
    # interactive mode with an empty project_name input would leave dependent
    # vars as empty strings even after _pick_project_name fills in a real name.
    for q in config.questions:
        if q.name == "project_name":
            continue
        if isinstance(q.default, str) and "project_name" in q.default:
            answers.render_vars[q.name] = _coerce_question_value(
                q, _render_copier_default(q.default, answers.render_vars)
            )

    project_dir = (Path.cwd() / project_name).resolve()

    if project_dir.exists():
        raise ZenitError(
            f"Directory '{project_dir}' already exists. "
            f"Choose a different project name or output directory."
        )

    step("Rendering template files")
    file_contributions = _render_template(template_dir)
    file_contributions, pending_tasks = _apply_safe_task_file_ops(
        file_contributions, config.tasks, answers.render_vars
    )

    step("Writing project")
    file_paths: list[str] = []
    with scaffold_or_rollback(project_dir):
        project_dir.mkdir(parents=True)

        for fc in file_contributions:
            if _uses_copier_internal_path_vars(fc.dest):
                warn(
                    f"Skipping '{fc.dest}' — destination depends on Copier-only "
                    f"variables (prefixed with _copier_)."
                )
                continue
            dest_path = project_dir / _render_destination_path(
                fc.dest, answers.render_vars
            )
            rel = str(dest_path.relative_to(project_dir))
            file_paths.append(rel)
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            if fc.content is not None:
                if fc.template:
                    try:
                        rendered = COPIER_ENV.from_string(fc.content).render(
                            **answers.render_vars
                        )
                        dest_path.write_text(rendered, encoding="utf-8")
                    except Exception:
                        warn(f"Failed to render '{fc.dest}' — copying verbatim.")
                        dest_path.write_text(fc.content, encoding="utf-8")
                else:
                    dest_path.write_text(fc.content, encoding="utf-8")
            elif fc.source is not None:
                shutil.copy2(fc.source, dest_path)

    step("Scanning project inventory")
    env_keys = _inventory_env(project_dir)
    compose_services, compose_volumes = _inventory_compose(project_dir)
    deps = _inventory_deps(project_dir)

    step("Writing manifest and lockfile")
    manifest = read_manifest(project_dir)

    for key in env_keys:
        add_env_entry(manifest, key, source=EntrySource.MIGRATED, addon="")
    for svc in compose_services:
        add_compose_service(manifest, svc, source=EntrySource.MIGRATED, addon="")
    for vol in compose_volumes:
        add_compose_volume(manifest, vol, source=EntrySource.MIGRATED, addon="")
    for pkg, spec, dev in deps:
        add_dependency(
            manifest, pkg, spec, source=EntrySource.MIGRATED, addon="", dev=dev
        )

    write_manifest(project_dir, manifest)

    migrated = MigratedMeta(
        source=template_source,
        has_tasks=bool(pending_tasks),
        file_paths=sorted(set(file_paths)),
    )
    write_lockfile(project_dir, f"migrated:{template_source}", [], migrated=migrated)

    step("Processing tasks")
    if pending_tasks:
        _write_task_stub(project_dir, pending_tasks)

    result = MigrationResult(
        project_dir=project_dir,
        template_source=template_source,
        file_paths=sorted(set(file_paths)),
        addon_ids=[],
        has_tasks=bool(pending_tasks),
        env_count=len(env_keys),
        compose_service_count=len(compose_services),
        compose_volume_count=len(compose_volumes),
        dep_count=len(deps),
    )

    # Clean up temp directory if we cloned
    _cleanup_temp(template_dir)

    return result


def _cleanup_temp(template_dir: Path) -> None:
    """Clean up a temporary directory if it's in the system temp dir."""
    tmp = Path(tempfile.gettempdir()).resolve()
    if template_dir.resolve().is_relative_to(tmp):
        shutil.rmtree(template_dir, ignore_errors=True)
