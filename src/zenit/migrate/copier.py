"""Copier template parser, question classifier, and file classifier."""

from __future__ import annotations

import contextlib
import fnmatch
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import jinja2
import jinja2.meta
from ruamel.yaml import YAML

from .env import COPIER_ENV, build_extended_env

# ── Question types ─────────────────────────────────────────────────────────────


class QuestionType(Enum):
    STR = "str"
    BOOL = "bool"
    INT = "int"
    FLOAT = "float"
    CHOICE = "choice"
    MULTISELECT = "multiselect"
    SECRET = "secret"
    YAML = "yaml"


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
    EXCLUDED = "excluded"


type CopierTask = str | dict[str, object]


# ── Data types ─────────────────────────────────────────────────────────────────


@dataclass
class CopierQuestion:
    name: str
    type: QuestionType
    default: Any = ""
    help: str = ""
    choices: list[str] = field(default_factory=list)
    choices_map: dict[str, str] = field(default_factory=dict)
    when: str | bool | None = None
    validator: str | None = None
    required: bool = False


@dataclass
class CopierConfig:
    questions: list[CopierQuestion] = field(default_factory=list)
    subdirectory: str | None = None
    exclude: list[str] = field(default_factory=list)
    skip_if_exists: list[str] = field(default_factory=list)
    tasks: list[CopierTask] = field(default_factory=list)
    jinja_extensions: list[str] = field(default_factory=list)
    templates_suffix: str | None = None
    envops: dict[str, Any] = field(default_factory=dict)
    message_before_copy: str = ""
    message_after_copy: str = ""


# ── Parser ─────────────────────────────────────────────────────────────────────


def _coerce_yaml_value(value: object) -> object:
    if not isinstance(value, str):
        return value
    if not value.strip():
        return ""
    try:
        parsed = YAML().load(value)
        return parsed if parsed is not None else value
    except Exception:
        return value


def _infer_question_type(raw: dict[str, Any]) -> QuestionType:
    if raw.get("multiselect"):
        return QuestionType.MULTISELECT
    type_str = raw.get("type", "str")
    choices = raw.get("choices")
    match type_str:
        case "secret":
            return QuestionType.SECRET
        case "yaml":
            return QuestionType.YAML
        case "bool":
            return QuestionType.BOOL
        case "int":
            return QuestionType.INT
        case "float":
            return QuestionType.FLOAT
        case _:
            if choices:
                return QuestionType.CHOICE
            return QuestionType.STR


def _build_copier_yaml(template_root: Path) -> YAML:
    yaml = YAML()

    def include_constructor(loader: Any, node: Any) -> Any:
        filename: str = loader.construct_scalar(node)
        included_path = template_root / filename
        if not included_path.exists():
            return {}
        inc_yaml = _build_copier_yaml(template_root)
        data = inc_yaml.load(included_path.read_text(encoding="utf-8"))
        return data or {}

    yaml.constructor.add_constructor("!include", include_constructor)
    return yaml


def parse_copier_yml(path: Path) -> CopierConfig:
    if not path.exists():
        raise FileNotFoundError(f"copier.yml not found at '{path}'")

    raw = path.read_text(encoding="utf-8")
    if not raw.strip():
        return CopierConfig()

    template_root = path.parent
    yaml = _build_copier_yaml(template_root)

    docs = list(yaml.load_all(raw))
    data: dict[str, Any] = {}
    for doc in docs:
        if doc is not None and isinstance(doc, dict):
            data.update(doc)

    config = CopierConfig()

    config.subdirectory = data.pop("_subdirectory", None)
    config.exclude = list(data.pop("_exclude", []) or [])
    config.skip_if_exists = list(data.pop("_skip_if_exists", []) or [])
    templates_suffix = data.pop("_templates_suffix", None)
    if isinstance(templates_suffix, str):
        config.templates_suffix = templates_suffix
    raw_tasks = data.pop("_tasks", []) or []
    if isinstance(raw_tasks, list):
        config.tasks = []
        for task in raw_tasks:
            if isinstance(task, (str, dict)):
                config.tasks.append(task)
            elif isinstance(task, bool):
                config.tasks.append(str(task).lower())
    config.jinja_extensions = list(data.pop("_jinja_extensions", []) or [])
    config.message_before_copy = str(data.pop("_message_before_copy", "") or "")
    config.message_after_copy = str(data.pop("_message_after_copy", "") or "")
    raw_envops = data.pop("_envops", None)
    if isinstance(raw_envops, dict):
        config.envops = raw_envops

    for key in list(data):
        if key.startswith("_"):
            data.pop(key)

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
        raw_choices = spec.get("choices")
        choices_list: list[str] = []
        choices_map: dict[str, str] = {}
        if isinstance(raw_choices, dict):
            for display_name, value in raw_choices.items():
                if isinstance(value, dict):
                    value = value.get("value", display_name)
                if not isinstance(value, str):
                    value = str(value)
                choices_list.append(display_name)
                choices_map[display_name] = value
        elif isinstance(raw_choices, list):
            choices_list = [
                str(c) if not isinstance(c, dict) else str(c.get("value", str(c)))
                for c in raw_choices
            ]
            choices_map = {c: c for c in choices_list}
        elif raw_choices:
            choices_list = [str(c) for c in raw_choices]
            choices_map = {c: c for c in choices_list}

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
            elif qtype == QuestionType.MULTISELECT:
                default = []
        config.questions.append(
            CopierQuestion(
                name=name,
                type=qtype,
                default=default,
                help=spec.get("help", ""),
                choices=choices_list,
                choices_map=choices_map,
                when=spec.get("when"),
                validator=spec.get("validator"),
                required=bool(spec.get("required", False)),
            )
        )

    return config


# ── Question classifier ────────────────────────────────────────────────────


def _get_undeclared_variables(content: str) -> set[str]:
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
        elif q.type in (QuestionType.MULTISELECT, QuestionType.CHOICE):
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


# ── File classifier ────────────────────────────────────────────────────────


def _has_jinja_expressions(content: str) -> bool:
    if not content.strip():
        return False
    return "{{" in content or "{%" in content or "{#" in content


def _excluded_by_pattern(
    file_path: Path, content_dir: Path | None, patterns: list[str]
) -> bool:
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


def _try_parse_with_env(
    content: str, env: jinja2.Environment, question_names: set[str]
) -> FileJinjaClass:
    try:
        ast = env.parse(content)
    except Exception:
        return FileJinjaClass.STATIC
    try:
        undeclared = jinja2.meta.find_undeclared_variables(ast)
    except Exception:
        return FileJinjaClass.STATIC
    if undeclared and (undeclared & question_names):
        return FileJinjaClass.JINJA2_TEMPLATE
    return FileJinjaClass.STATIC


def classify_file(
    file_path: Path,
    config: CopierConfig,
    content_dir: Path | None = None,
    template_dir: Path | None = None,
) -> FileJinjaClass:
    if _excluded_by_pattern(file_path, content_dir, config.exclude):
        return FileJinjaClass.EXCLUDED

    env: jinja2.Environment
    if config.jinja_extensions or config.envops:
        env = build_extended_env(config, template_dir)
    else:
        env = COPIER_ENV
    question_names = {q.name for q in config.questions}

    suffix = config.templates_suffix
    if suffix is not None:
        name = file_path.name
        if name.endswith(suffix):
            try:
                content = file_path.read_text(encoding="utf-8")
            except Exception:
                return FileJinjaClass.STATIC
            if (
                _try_parse_with_env(content, env, question_names)
                == FileJinjaClass.JINJA2_TEMPLATE
            ):
                return FileJinjaClass.JINJA2_TEMPLATE
            if config.jinja_extensions:
                return FileJinjaClass.UNTRANSLATABLE
            return FileJinjaClass.JINJA2_TEMPLATE
        return FileJinjaClass.STATIC

    if file_path.suffix in (".jinja", ".j2", ".jinja2"):
        try:
            content = file_path.read_text(encoding="utf-8")
        except Exception:
            return FileJinjaClass.STATIC
        if (
            _try_parse_with_env(content, env, question_names)
            == FileJinjaClass.JINJA2_TEMPLATE
        ):
            return FileJinjaClass.JINJA2_TEMPLATE
        if config.jinja_extensions:
            return FileJinjaClass.UNTRANSLATABLE
        return FileJinjaClass.JINJA2_TEMPLATE

    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception:
        return FileJinjaClass.STATIC

    if not _has_jinja_expressions(content):
        return FileJinjaClass.STATIC

    return _try_parse_with_env(content, env, question_names)
