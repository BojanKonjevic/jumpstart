"""Copier template parser, question classifier, and delimiter translator."""

from __future__ import annotations

import contextlib
import fnmatch
import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import jinja2
import jinja2.meta
import yaml

# ── Question types ─────────────────────────────────────────────────────────────


class QuestionType(Enum):
    STR = "str"
    BOOL = "bool"
    INT = "int"
    FLOAT = "float"
    CHOICE = "choice"


class QuestionClass(Enum):
    RENDER_VAR = "render_var"
    ADDON_CANDIDATE = "addon"
    PARTIAL_ADDON = "partial_addon"
    CHOICE_VAR = "choice_var"
    UNCLASSIFIABLE = "unknown"


class FileJinjaClass(Enum):
    JINJA2_TEMPLATE = "jinja2"
    STATIC = "static"
    UNTRANSLATABLE = "untranslatable"


type CopierTask = str | dict[str, object]


# ── Data types ─────────────────────────────────────────────────────────────────


@dataclass
class CopierQuestion:
    name: str
    type: QuestionType
    default: Any = ""
    help: str = ""
    choices: list[str] = field(default_factory=list)
    when: str | None = None


@dataclass
class CopierConfig:
    questions: list[CopierQuestion] = field(default_factory=list)
    subdirectory: str | None = None
    exclude: list[str] = field(default_factory=list)
    skip_if_exists: list[str] = field(default_factory=list)
    tasks: list[CopierTask] = field(default_factory=list)
    jinja_extensions: list[str] = field(default_factory=list)


def _to_nice_yaml(value: object, indent: int = 2) -> str:
    """Serialize a Python object to YAML (``to_nice_yaml`` filter)."""
    result = yaml.dump(
        value, default_flow_style=False, indent=indent, allow_unicode=True
    )
    return result.rstrip("\n")


def _to_nice_json(value: object, indent: int = 2) -> str:
    """Serialize a Python object to pretty-printed JSON (``to_nice_json`` filter)."""
    return json.dumps(value, indent=indent, ensure_ascii=False)


# ── Copier delimiters (standard Jinja2) ────────────────────────────────────────

COPIER_ENV = jinja2.Environment(
    variable_start_string="{{",
    variable_end_string="}}",
    block_start_string="{%",
    block_end_string="%}",
    comment_start_string="{#",
    comment_end_string="#}",
    keep_trailing_newline=True,
)
COPIER_ENV.filters["to_nice_yaml"] = _to_nice_yaml
COPIER_ENV.filters["to_nice_json"] = _to_nice_json


# ── Parser ─────────────────────────────────────────────────────────────────────


def _infer_question_type(raw: dict[str, Any]) -> QuestionType:
    type_str = raw.get("type", "str")
    choices = raw.get("choices")
    if choices:
        return QuestionType.CHOICE
    match type_str:
        case "bool":
            return QuestionType.BOOL
        case "int":
            return QuestionType.INT
        case "float":
            return QuestionType.FLOAT
        case _:
            return QuestionType.STR


def parse_copier_yml(path: Path) -> CopierConfig:
    """Parse a ``copier.yml`` file into a ``CopierConfig``."""
    if not path.exists():
        raise FileNotFoundError(f"copier.yml not found at '{path}'")

    raw = path.read_text(encoding="utf-8")
    if not raw.strip():
        return CopierConfig()

    data: dict[str, Any] = yaml.safe_load(raw) or {}

    config = CopierConfig()

    # Extract special underscore-prefixed keys
    config.subdirectory = data.pop("_subdirectory", None)
    config.exclude = list(data.pop("_exclude", []) or [])
    config.skip_if_exists = list(data.pop("_skip_if_exists", []) or [])
    raw_tasks = data.pop("_tasks", []) or []
    if isinstance(raw_tasks, list):
        config.tasks = [task for task in raw_tasks if isinstance(task, (str, dict))]
    config.jinja_extensions = list(data.pop("_jinja_extensions", []) or [])

    for name, spec in data.items():
        if not isinstance(spec, dict):
            config.questions.append(
                CopierQuestion(
                    name=name,
                    type=QuestionType.STR,
                    default=spec if spec is not None else "",
                    help="",
                )
            )
            continue
        qtype = _infer_question_type(spec)
        default = spec.get("default")
        if default is None:
            if qtype == QuestionType.STR:
                default = ""
            elif qtype == QuestionType.BOOL:
                default = False
            elif qtype == QuestionType.INT:
                default = 0
            elif qtype == QuestionType.FLOAT:
                default = 0.0
        config.questions.append(
            CopierQuestion(
                name=name,
                type=qtype,
                default=default,
                help=spec.get("help", ""),
                choices=list(spec.get("choices", []) or []),
                when=spec.get("when"),
            )
        )

    return config


# ── Question classifier ────────────────────────────────────────────────────────


def _get_undeclared_variables(content: str) -> set[str]:
    """Extract undeclared variable names referenced in a Jinja2 template string.

    Uses ``jinja2.meta.find_undeclared_variables`` which returns all variable
    names that are referenced but not defined locally in the template.
    """
    try:
        ast = COPIER_ENV.parse(content)
    except Exception:
        return set()
    try:
        return jinja2.meta.find_undeclared_variables(ast)
    except Exception:
        return set()


def classify_questions(
    config: CopierConfig, template_dir: Path
) -> dict[str, QuestionClass]:
    """Classify each Copier question into a zenit question class.

    Uses the template directory to scan files for variable references
    to determine gating patterns.
    """
    classes: dict[str, QuestionClass] = {}

    question_names: set[str] = {q.name for q in config.questions}
    question_files: dict[str, set[str]] = {q.name: set() for q in config.questions}
    file_variables: dict[str, set[str]] = {}

    if template_dir.exists():
        for f in template_dir.rglob("*"):
            if not f.is_file():
                continue
            if f.parent.name == ".git" or f.name == ".git":
                continue
            try:
                content = f.read_text(encoding="utf-8")
            except Exception:
                continue
            vars_in_file = _get_undeclared_variables(content)
            if not vars_in_file:
                continue
            rel = str(f.relative_to(template_dir))
            file_variables[rel] = vars_in_file
            matched_qs = {v for v in vars_in_file if v in question_names}
            for qname in matched_qs:
                question_files[qname].add(rel)

    bool_q_names = {q.name for q in config.questions if q.type == QuestionType.BOOL}

    for q in config.questions:
        if q.type in (QuestionType.STR, QuestionType.INT, QuestionType.FLOAT):
            classes[q.name] = QuestionClass.RENDER_VAR
        elif q.type == QuestionType.CHOICE:
            classes[q.name] = QuestionClass.CHOICE_VAR
        elif q.type == QuestionType.BOOL:
            files = question_files.get(q.name, set())
            if not files:
                classes[q.name] = QuestionClass.RENDER_VAR
            else:
                has_other_bool = False
                for file_rel in files:
                    fvars = file_variables.get(file_rel, set())
                    other_bools = {
                        v for v in fvars if v in bool_q_names and v != q.name
                    }
                    if other_bools:
                        has_other_bool = True
                        break
                if has_other_bool:
                    classes[q.name] = QuestionClass.PARTIAL_ADDON
                else:
                    classes[q.name] = QuestionClass.ADDON_CANDIDATE
        else:
            classes[q.name] = QuestionClass.UNCLASSIFIABLE

    return classes


# ── File classifier ────────────────────────────────────────────────────────────


def _has_jinja_expressions(content: str) -> bool:
    """Check if a string contains Jinja2 expressions using Copier's delimiters."""
    if not content.strip():
        return False
    return "{{" in content or "{%" in content or "{#" in content


def _excluded_by_pattern(
    file_path: Path, content_dir: Path | None, patterns: list[str]
) -> bool:
    """Check if *file_path* matches any exclude pattern.

    Copier's ``_exclude`` patterns match against paths relative to the
    content directory (or the template root when there is no subdirectory).
    """
    if not patterns:
        return False
    rel_str: str | None = None
    if content_dir is not None:
        with contextlib.suppress(ValueError):
            rel_str = str(file_path.relative_to(content_dir))
    candidates = [p for p in (rel_str, str(file_path), file_path.name) if p is not None]
    for pattern in patterns:
        for candidate in candidates:
            if fnmatch.fnmatch(candidate, pattern):
                return True
    return False


def classify_file(
    file_path: Path, config: CopierConfig, content_dir: Path | None = None
) -> FileJinjaClass:
    """Classify a single file as JINJA2, STATIC, or UNTRANSLATABLE.

    1. If the file matches an exclude pattern, skip (STATIC). Patterns are
       matched against the path relative to *content_dir* when available,
       falling back to the full path and then the filename. This matches
       Copier's behavior where ``_exclude`` patterns are relative-path based.
    2. If the file has a .jinja, .j2, or .jinja2 extension, it is a template.
    3. If ``jinja_extensions`` is non-empty, mark as UNTRANSLATABLE.
    4. Otherwise, attempt to parse with Jinja2. If parsing succeeds and the AST
       contains expressions, treat as JINJA2. Otherwise STATIC.
    """
    if _excluded_by_pattern(file_path, content_dir, config.exclude):
        return FileJinjaClass.STATIC

    if file_path.suffix in (".jinja", ".j2", ".jinja2"):
        if config.jinja_extensions:
            return FileJinjaClass.UNTRANSLATABLE
        return FileJinjaClass.JINJA2_TEMPLATE

    if config.jinja_extensions:
        return FileJinjaClass.UNTRANSLATABLE

    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception:
        return FileJinjaClass.STATIC

    if not _has_jinja_expressions(content):
        return FileJinjaClass.STATIC

    try:
        ast = COPIER_ENV.parse(content)
    except Exception:
        return FileJinjaClass.STATIC

    try:
        undeclared = jinja2.meta.find_undeclared_variables(ast)
    except Exception:
        return FileJinjaClass.STATIC

    if undeclared:
        question_names = {q.name for q in config.questions}
        if undeclared & question_names:
            return FileJinjaClass.JINJA2_TEMPLATE

    return FileJinjaClass.STATIC
