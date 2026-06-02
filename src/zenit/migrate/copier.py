"""Copier template parser, question classifier, and delimiter translator."""

from __future__ import annotations

import contextlib
import fnmatch
import json
import secrets
import string
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from io import StringIO
from pathlib import Path
from typing import Any

import jinja2
import jinja2.ext
import jinja2.meta
import jinja2.nodes
import jinja2.parser
from ruamel.yaml import YAML

from zenit.cli.ui import warn

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


def _to_nice_yaml(value: object, indent: int = 2) -> str:
    """Serialize a Python object to YAML (``to_nice_yaml`` filter)."""
    y = YAML()
    y.default_flow_style = False
    y.indent(mapping=indent, sequence=indent, offset=indent)
    buf = StringIO()
    y.dump(value, buf)
    return buf.getvalue().rstrip("\n")


def _to_nice_json(value: object, indent: int = 2) -> str:
    """Serialize a Python object to pretty-printed JSON (``to_nice_json`` filter)."""
    return json.dumps(value, indent=indent, ensure_ascii=False)


# ── Copier Jinja2 namespace extension ─────────────────────────────────────────


class CopierNamespaceExtension(jinja2.ext.Extension):
    """Handle ``{% namespace name %}``/``{% endnamespace %}`` blocks.

    Copier templates use this extension to group variables under a prefix.
    The extension was originally provided by ``copier.template`` and is
    registered here as a standalone Jinja2 extension class.
    """

    tags = {"namespace", "endnamespace"}

    def parse(self, parser: jinja2.parser.Parser) -> jinja2.nodes.Node:
        # ``{% endnamespace %}`` — consume the name token, return empty output.
        if parser.stream.current.value == "endnamespace":
            next(parser.stream)
            return jinja2.nodes.Output([])
        # ``{% namespace name %}`` — consume tag name, then the group name.
        next(parser.stream)
        token = parser.stream.expect("name")
        name = token.value
        body = parser.parse_statements(
            ("name:endnamespace",),
            drop_needle=True,
        )
        return jinja2.nodes.CallBlock(
            self.call_method("_render_namespace", [jinja2.nodes.Const(name)]),
            [],
            [],
            body,
        )

    @staticmethod
    def _render_namespace(name: str, caller: Callable[[], str]) -> str:
        return caller()


# ── Safe stubs for security-sensitive Jinja2 features ─────────────────────────


def _safe_shell_filter(command: str) -> str:
    """Safe stub for the ``shell()`` Jinja2 filter.

    The real ``shell()`` filter (from ``jinja2_shell_extension``) executes
    shell commands during rendering — a security concern in migration
    context.  This stub warns and returns an empty string.
    """
    warn(
        f"shell() filter called with: '{command[:80]}"
        f"{'...' if len(command) > 80 else ''}'. "
        f"Shell execution during rendering is not supported. "
        f"Returning empty string — provide the value with "
        f"-D <name>=<value>."
    )
    return ""


def _make_secret(length: int = 32) -> str:
    """Generate a random alphanumeric string (replaces Copier's ``make_secret()``)."""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


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

COPIER_ENV.add_extension("jinja2.ext.do")
COPIER_ENV.add_extension("jinja2.ext.loopcontrols")
COPIER_ENV.add_extension(CopierNamespaceExtension)
COPIER_ENV.filters["shell"] = _safe_shell_filter
COPIER_ENV.globals["make_secret"] = _make_secret


def build_extended_env(
    config: CopierConfig,
    template_dir: Path | None = None,
    content_dir: Path | None = None,
) -> jinja2.Environment:
    """Build a Jinja2 environment that includes envops and custom extensions.

    Applies ``_envops`` parameters (custom Jinja2 delimiters, whitespace
    control, etc.) when specified in the template config, and tries to
    import each extension in ``config.jinja_extensions``.

    For local extension modules (e.g. ``extensions/slugify.py:SlugifyExtension``),
    *template_dir* is added to ``sys.path`` during import.

    When *content_dir* is provided, a ``FileSystemLoader`` pointing to it is
    attached so that ``{% import %}`` and ``{% extends %}`` resolve correctly.
    """
    env_kw: dict[str, Any] = {
        "variable_start_string": "{{",
        "variable_end_string": "}}",
        "block_start_string": "{%",
        "block_end_string": "%}",
        "comment_start_string": "{#",
        "comment_end_string": "#}",
        "keep_trailing_newline": True,
    }
    env_kw.update(config.envops)

    env = jinja2.Environment(**env_kw)
    env.filters["to_nice_yaml"] = _to_nice_yaml
    env.filters["to_nice_json"] = _to_nice_json

    # Standard extensions (Phase 2, Step 2)
    env.add_extension("jinja2.ext.do")
    env.add_extension("jinja2.ext.loopcontrols")
    env.add_extension(CopierNamespaceExtension)
    env.filters["shell"] = _safe_shell_filter
    env.globals["make_secret"] = _make_secret

    if content_dir is not None:
        search_paths = [str(content_dir.resolve())]
        if template_dir is not None:
            search_paths.append(str(template_dir.resolve()))
        env.loader = jinja2.FileSystemLoader(search_paths)

    if config.jinja_extensions and template_dir is not None:
        template_dir_str = str(template_dir.resolve())
        if template_dir_str not in sys.path:
            sys.path.insert(0, template_dir_str)

    for ext_path in config.jinja_extensions:
        try:
            env.add_extension(ext_path)
        except Exception as e:
            warn(
                f"Failed to load Jinja2 extension '{ext_path}': {e}. "
                f"Files requiring this extension may render incompletely. "
                f"Install the extension package and re-run, or provide "
                f"values with -D <name>=<value>."
            )

    return env


# ── Parser ─────────────────────────────────────────────────────────────────────


def _coerce_yaml_value(value: object) -> object:
    """Parse a YAML string into a Python object."""
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
    if choices:
        return QuestionType.CHOICE
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
            return QuestionType.STR


def _build_copier_yaml(template_root: Path) -> YAML:
    """Build a YAML instance with ``!include`` support for multi-file configs."""
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
    """Parse a ``copier.yml`` file into a ``CopierConfig``."""
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

    # Extract special underscore-prefixed keys
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

    # Remove remaining Copier metadata keys that aren't questions
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


def _try_parse_with_env(
    content: str, env: jinja2.Environment, question_names: set[str]
) -> FileJinjaClass:
    """Try to parse *content* with *env* and classify based on undeclared variables."""
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
    """Classify a single file as JINJA2, STATIC, or UNTRANSLATABLE.

    1. If the file matches an exclude pattern, skip (STATIC). Patterns are
       matched against the path relative to *content_dir* when available,
       falling back to the full path and then the filename. This matches
       Copier's behavior where ``_exclude`` patterns are relative-path based.
    2. If ``_templates_suffix`` is set, only files ending with that suffix
       are candidates for Jinja2 template classification.  All other files
       are STATIC.
    3. If the file has a .jinja, .j2, or .jinja2 extension, treat as JINJA2.
    4. If ``jinja_extensions`` is non-empty and the file requires custom
       extensions to parse/render, mark as UNTRANSLATABLE.
    5. Otherwise, attempt to parse with Jinja2. If parsing succeeds and the AST
       contains expressions referencing known questions, treat as JINJA2.
       Otherwise STATIC.
    """
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
        # Custom _templates_suffix — only files with this suffix are templates
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
