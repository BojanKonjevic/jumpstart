"""Jinja2 environment setup for Copier template rendering."""

from __future__ import annotations

import datetime
import importlib
import json
import re
import secrets
import string
import sys
from collections.abc import Callable
from io import StringIO
from pathlib import Path
from typing import TYPE_CHECKING, Any

import jinja2
import jinja2.ext
import jinja2.meta
import jinja2.nodes
import jinja2.parser
from ruamel.yaml import YAML

from zenit.cli.ui import warn

if TYPE_CHECKING:
    from .copier import CopierConfig


# ── Helper filters ──────────────────────────────────────────────────────────────


def _to_nice_yaml(value: object, indent: int = 2) -> str:
    y = YAML()
    y.default_flow_style = False
    y.indent(mapping=indent, sequence=indent, offset=indent)
    buf = StringIO()
    y.dump(value, buf)
    return buf.getvalue().rstrip("\n")


def _to_nice_json(value: object, indent: int = 2) -> str:
    return json.dumps(value, indent=indent, ensure_ascii=False)


def _slugify(value: str, sep: str = "-") -> str:
    value = value.lower().strip()
    value = re.sub(r"[^\w\s" + re.escape(sep) + "]", "", value)
    value = re.sub(r"[\s" + re.escape(sep) + r"]+", sep, value)
    return value.strip(sep)


def _strftime(value: object, fmt: str | None = None) -> str:
    if isinstance(value, str) and fmt is None:
        return datetime.datetime.now().strftime(value)
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.strftime(fmt) if fmt else str(value)
    return str(value)


def _commit_hash_url(value: str, repo_url: str) -> str:
    commit = str(value)[:40] if value else "HEAD"
    return f"{repo_url.rstrip('/')}/commit/{commit}"


def _to_json(value: object, indent: int | None = None) -> str:
    return json.dumps(value, indent=indent, ensure_ascii=False, default=str)


# ── Copier Jinja2 namespace extension ─────────────────────────────────────────


class CopierNamespaceExtension(jinja2.ext.Extension):
    tags = {"namespace", "endnamespace"}

    def parse(self, parser: jinja2.parser.Parser) -> jinja2.nodes.Node:
        if parser.stream.current.value == "endnamespace":
            next(parser.stream)
            return jinja2.nodes.Output([])
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


class CopierTimeExtension(jinja2.ext.Extension):
    tags = {"now"}

    def parse(self, parser: jinja2.parser.Parser) -> jinja2.nodes.Node:
        next(parser.stream)
        args: list[jinja2.nodes.Expr] = []
        while parser.stream.current.type != "block_end":
            if parser.stream.current.test("comma"):
                next(parser.stream)
                continue
            args.append(parser.parse_expression())
        return jinja2.nodes.Output(
            [
                self.call_method("_render_now", args),
            ]
        )

    @staticmethod
    def _render_now(tz: str = "utc", fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
        if tz.lower() in ("utc", "gmt"):
            now = datetime.datetime.now(datetime.UTC)
        else:
            now = datetime.datetime.now()
        return now.strftime(fmt)


# ── Safe stubs for security-sensitive Jinja2 features ─────────────────────────


def _safe_shell_filter(command: str) -> str:
    warn(
        f"shell() filter called with: '{command[:80]}"
        f"{'...' if len(command) > 80 else ''}'. "
        f"Shell execution during rendering is not supported. "
        f"Returning empty string - provide the value with "
        f"-D <name>=<value>."
    )
    return ""


def _make_secret(length: int = 32) -> str:
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

COPIER_ENV.globals["_copier_conf"] = {
    "src_path": "/stub",
    "dst_path": "/stub",
    "answers_path": ".copier-answers.yml",
    "vcs_ref": "HEAD",
    "exclude": [],
    "skip_if_exists": [],
    "tasks": [],
    "templates_suffix": None,
    "jinja_extensions": [],
    "envops": {},
    "subdirectory": None,
}
COPIER_ENV.globals["_copier_answers"] = {
    "_src_path": "/stub",
    "_dst_path": "/stub",
}
COPIER_ENV.globals["_folder_name"] = "project"
COPIER_ENV.globals["_destination_path"] = "/stub/project"
COPIER_ENV.globals["now"] = datetime.datetime.now

COPIER_ENV.filters["slugify"] = _slugify
COPIER_ENV.filters["strftime"] = _strftime
COPIER_ENV.filters["commit_hash_url"] = _commit_hash_url
COPIER_ENV.filters["to_json"] = _to_json

COPIER_ENV.add_extension(CopierTimeExtension)


# ── Extension loading helpers ──────────────────────────────────────────────────


class _CopierTemplateExtensionLoader(jinja2.ext.Extension):
    tags = set()

    def parse(self, parser: jinja2.parser.Parser) -> jinja2.nodes.Node:
        return jinja2.nodes.Output([])


def _load_extension(
    env: jinja2.Environment,
    ext_path: str,
    template_dir: Path | None = None,
) -> None:
    _MISSING_PACKAGE_STUBS: dict[str, type[jinja2.ext.Extension]] = {
        "copier_template_extensions.TemplateExtensionLoader": (
            _CopierTemplateExtensionLoader
        ),
    }
    if ext_path in _MISSING_PACKAGE_STUBS:
        env.add_extension(_MISSING_PACKAGE_STUBS[ext_path])
        return

    try:
        env.add_extension(ext_path)
        return
    except (ImportError, AttributeError):
        pass

    if ":" in ext_path:
        module_part, class_name = ext_path.rsplit(":", 1)
    else:
        module_part = ext_path
        class_name = None

    if module_part.endswith(".py"):
        module_part = module_part[:-3]

    module_part = module_part.replace("/", ".").replace("\\", ".")

    if template_dir is not None:
        d = str(template_dir.resolve())
        if d not in sys.path:
            sys.path.insert(0, d)

    try:
        mod = importlib.import_module(module_part)
    except ImportError as e:
        raise ImportError(
            f"Cannot import module '{module_part}' (from '{ext_path}'): {e}"
        ) from e

    if class_name:
        ext_cls: type[jinja2.ext.Extension] = getattr(mod, class_name)
    else:
        ext_cls = _find_extension_class(mod)

    env.add_extension(ext_cls)


def _find_extension_class(mod: object) -> type[jinja2.ext.Extension]:
    mod_name = getattr(mod, "__name__", None)
    for name in dir(mod):
        obj = getattr(mod, name, None)
        if (
            isinstance(obj, type)
            and issubclass(obj, jinja2.ext.Extension)
            and obj is not jinja2.ext.Extension
            and getattr(obj, "__module__", None) == mod_name
        ):
            return obj
    fallback = getattr(mod, "Extension", None)
    if isinstance(fallback, type) and issubclass(fallback, jinja2.ext.Extension):
        return fallback
    raise ImportError(f"No jinja2.ext.Extension subclass found in module '{mod_name}'")


def build_extended_env(
    config: CopierConfig,
    template_dir: Path | None = None,
    content_dir: Path | None = None,
) -> jinja2.Environment:
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

    env.add_extension("jinja2.ext.do")
    env.add_extension("jinja2.ext.loopcontrols")
    env.add_extension(CopierNamespaceExtension)
    env.filters["shell"] = _safe_shell_filter
    env.globals["make_secret"] = _make_secret

    env.globals["_copier_conf"] = COPIER_ENV.globals["_copier_conf"]
    env.globals["_copier_answers"] = COPIER_ENV.globals["_copier_answers"]
    env.globals["_folder_name"] = "project"
    env.globals["_destination_path"] = "/stub/project"
    env.globals["now"] = datetime.datetime.now

    env.filters["slugify"] = _slugify
    env.filters["strftime"] = _strftime
    env.filters["commit_hash_url"] = _commit_hash_url
    env.filters["to_json"] = _to_json

    env.add_extension(CopierTimeExtension)

    if content_dir is not None:
        search_paths = [str(content_dir.resolve())]
        if template_dir is not None:
            search_paths.append(str(template_dir.resolve()))
        env.loader = jinja2.FileSystemLoader(search_paths)

    _stubs_dir = Path(__file__).resolve().parent / "_ext_stubs"
    _stubs_dir_str = str(_stubs_dir)
    if _stubs_dir_str not in sys.path:
        sys.path.insert(0, _stubs_dir_str)

    for ext_path in config.jinja_extensions:
        try:
            _load_extension(env, ext_path, template_dir)
        except Exception as e:
            warn(
                f"Failed to load Jinja2 extension '{ext_path}': {e}. "
                f"Files requiring this extension may render incompletely. "
                f"Install the extension package and re-run, or provide "
                f"values with -D <name>=<value>."
            )

    return env


# ── Default rendering ──────────────────────────────────────────────────────────


def _render_copier_default(
    value: object,
    render_vars: dict[str, Any],
) -> object:
    if isinstance(value, list):
        return [_render_copier_default(item, render_vars) for item in value]
    if not isinstance(value, str):
        return value
    if "{{" not in value and "{%" not in value and "{#" not in value:
        return value
    try:
        return COPIER_ENV.from_string(value).render(**render_vars)
    except Exception:
        return value
