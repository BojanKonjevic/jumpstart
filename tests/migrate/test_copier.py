"""Tests for Copier YAML parsing, question classification, and delimiter swap."""

import re
from pathlib import Path

import pytest
import yaml

from zenit.migrate.copier import (
    COPIER_ENV,
    CopierConfig,
    FileJinjaClass,
    QuestionClass,
    QuestionType,
    _coerce_yaml_value,
    _make_secret,
    _safe_shell_filter,
    build_extended_env,
    classify_file,
    classify_questions,
    parse_copier_yml,
)

# ── parse_copier_yml ───────────────────────────────────────────────────────────


def test_parse_simple_copier_yml(tmp_path: Path) -> None:
    data = {
        "project_name": {"type": "str", "help": "Your project name"},
        "use_redis": {"type": "bool", "default": False, "help": "Add Redis?"},
    }
    path = tmp_path / "copier.yml"
    path.write_text(yaml.dump(data))
    config = parse_copier_yml(path)
    assert len(config.questions) == 2
    assert config.questions[0].name == "project_name"
    assert config.questions[0].type == QuestionType.STR
    assert config.questions[1].name == "use_redis"
    assert config.questions[1].type == QuestionType.BOOL
    assert config.questions[1].default is False


def test_parse_all_question_types(tmp_path: Path) -> None:
    data = {
        "name": {"type": "str", "help": "Name"},
        "count": {"type": "int", "default": 3, "help": "Count"},
        "rate": {"type": "float", "default": 1.5, "help": "Rate"},
        "enabled": {"type": "bool", "default": True, "help": "Enabled?"},
        "db": {
            "type": "str",
            "choices": ["postgres", "mysql"],
            "help": "DB choice",
        },
    }
    path = tmp_path / "copier.yml"
    path.write_text(yaml.dump(data))
    config = parse_copier_yml(path)
    types = {q.name: q.type for q in config.questions}
    assert types["name"] == QuestionType.STR
    assert types["count"] == QuestionType.INT
    assert types["rate"] == QuestionType.FLOAT
    assert types["enabled"] == QuestionType.BOOL
    assert types["db"] == QuestionType.CHOICE


def test_parse_special_keys(tmp_path: Path) -> None:
    data = {
        "project_name": {"type": "str", "help": "Name"},
        "_subdirectory": "app",
        "_exclude": ["*.md", "*.txt"],
        "_skip_if_exists": ["config.py"],
        "_tasks": ["echo hello", "pip install -r requirements.txt"],
        "_jinja_extensions": ["jinja2.ext.i18n"],
    }
    path = tmp_path / "copier.yml"
    path.write_text(yaml.dump(data))
    config = parse_copier_yml(path)
    assert config.subdirectory == "app"
    assert config.exclude == ["*.md", "*.txt"]
    assert config.skip_if_exists == ["config.py"]
    assert config.tasks == ["echo hello", "pip install -r requirements.txt"]
    assert config.jinja_extensions == ["jinja2.ext.i18n"]
    # Only non-underscore keys are questions
    assert len(config.questions) == 1


def test_parse_default_handling(tmp_path: Path) -> None:
    data = {
        "name": {"type": "str", "help": "Name"},
        "flag": {"type": "bool", "default": True, "help": "Flag"},
    }
    path = tmp_path / "copier.yml"
    path.write_text(yaml.dump(data))
    config = parse_copier_yml(path)
    q_name = [q for q in config.questions if q.name == "name"][0]
    q_flag = [q for q in config.questions if q.name == "flag"][0]
    # str with no default should default to empty string
    assert q_name.default == ""
    assert q_flag.default is True


def test_parse_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        parse_copier_yml(tmp_path / "copier.yml")


def test_parse_empty_yml(tmp_path: Path) -> None:
    path = tmp_path / "copier.yml"
    path.write_text("")
    config = parse_copier_yml(path)
    assert config.questions == []
    assert config.tasks == []


def test_parse_secret_type(tmp_path: Path) -> None:
    """secret type is parsed as QuestionType.SECRET."""
    path = tmp_path / "copier.yml"
    path.write_text(yaml.dump({"api_key": {"type": "secret", "help": "API key"}}))
    config = parse_copier_yml(path)
    assert config.questions[0].type == QuestionType.SECRET


def test_parse_yaml_type(tmp_path: Path) -> None:
    """yaml type is parsed as QuestionType.YAML."""
    path = tmp_path / "copier.yml"
    path.write_text(yaml.dump({"config": {"type": "yaml", "help": "Config"}}))
    config = parse_copier_yml(path)
    assert config.questions[0].type == QuestionType.YAML


# ── _coerce_yaml_value ──────────────────────────────────────────────────────────


def test_coerce_yaml_value_dict() -> None:
    """YAML string with key-value pairs parses to a dict."""
    result = _coerce_yaml_value("key: value\nnested:\n  a: 1\n")
    assert isinstance(result, dict)
    assert result["key"] == "value"
    assert result["nested"]["a"] == 1


def test_coerce_yaml_value_list() -> None:
    """YAML list string parses to a list."""
    result = _coerce_yaml_value("- one\n- two\n- three\n")
    assert result == ["one", "two", "three"]


def test_coerce_yaml_value_plain_string() -> None:
    """Non-YAML string returns as-is."""
    result = _coerce_yaml_value("hello world")
    assert result == "hello world"


def test_coerce_yaml_value_empty() -> None:
    """Empty string returns empty string."""
    result = _coerce_yaml_value("")
    assert result == ""


def test_coerce_yaml_value_non_string() -> None:
    """Non-string value passes through unchanged."""
    result = _coerce_yaml_value(42)
    assert result == 42


# ── classify_questions ─────────────────────────────────────────────────────────


def test_classify_string_as_render_var(tmp_path: Path) -> None:
    data = {"project_name": {"type": "str", "help": "Name"}}
    path = tmp_path / "copier.yml"
    path.write_text(yaml.dump(data))
    config = parse_copier_yml(path)
    classes = classify_questions(config, tmp_path)
    assert classes["project_name"] == QuestionClass.RENDER_VAR


def test_classify_choice_as_choice_var(tmp_path: Path) -> None:
    data = {
        "db": {
            "type": "str",
            "choices": ["postgres", "mysql"],
            "help": "DB",
        }
    }
    path = tmp_path / "copier.yml"
    path.write_text(yaml.dump(data))
    config = parse_copier_yml(path)
    classes = classify_questions(config, tmp_path)
    assert classes["db"] == QuestionClass.CHOICE_VAR


def test_classify_int_as_render_var(tmp_path: Path) -> None:
    data = {"port": {"type": "int", "default": 8000, "help": "Port"}}
    path = tmp_path / "copier.yml"
    path.write_text(yaml.dump(data))
    config = parse_copier_yml(path)
    classes = classify_questions(config, tmp_path)
    assert classes["port"] == QuestionClass.RENDER_VAR


def test_classify_bool_with_exclusive_files_as_addon(tmp_path: Path) -> None:
    """A boolean question that exclusively gates a set of files → ADDON_CANDIDATE."""
    (tmp_path / "redis.yml.jinja").write_text(
        "{{ 'redis config' if use_redis else '' }}"
    )
    data = {
        "use_redis": {"type": "bool", "default": False, "help": "Add Redis?"},
    }
    path = tmp_path / "copier.yml"
    path.write_text(yaml.dump(data))
    config = parse_copier_yml(path)
    classes = classify_questions(config, tmp_path)
    assert classes["use_redis"] == QuestionClass.ADDON_CANDIDATE


def test_classify_bool_with_mixed_conditionals_as_partial(tmp_path: Path) -> None:
    """A boolean question sharing files with another boolean → PARTIAL_ADDON."""
    (tmp_path / "config.py.jinja").write_text("{{ use_redis }}{{ use_postgres }}")
    data = {
        "use_redis": {"type": "bool", "default": False, "help": "Add Redis?"},
        "use_postgres": {"type": "bool", "default": False, "help": "Add Postgres?"},
    }
    path = tmp_path / "copier.yml"
    path.write_text(yaml.dump(data))
    config = parse_copier_yml(path)
    classes = classify_questions(config, tmp_path)
    assert classes["use_redis"] == QuestionClass.PARTIAL_ADDON


def test_classify_bool_with_no_linked_files_as_render_var(tmp_path: Path) -> None:
    """A boolean question that gates no files at all → RENDER_VAR."""
    (tmp_path / "main.py.jinja").write_text("print('hello')")
    data = {
        "verbose": {"type": "bool", "default": False, "help": "Verbose?"},
    }
    path = tmp_path / "copier.yml"
    path.write_text(yaml.dump(data))
    config = parse_copier_yml(path)
    classes = classify_questions(config, tmp_path)
    assert classes["verbose"] == QuestionClass.RENDER_VAR


# ── classify_file ──────────────────────────────────────────────────────────────


def test_classify_static_no_jinja(tmp_path: Path) -> None:
    p = tmp_path / "readme.md"
    p.write_text("# Hello")
    from zenit.migrate.copier import CopierConfig

    cfg = CopierConfig(
        questions=[],
        subdirectory=None,
        exclude=[],
        skip_if_exists=[],
        tasks=[],
        jinja_extensions=[],
    )
    result = classify_file(p, cfg)
    assert result == FileJinjaClass.STATIC


def test_classify_jinja_with_variable(tmp_path: Path) -> None:
    p = tmp_path / "main.py.jinja"
    p.write_text("name = {{ project_name }}\n")
    from zenit.migrate.copier import CopierConfig

    cfg = CopierConfig(
        questions=[],
        subdirectory=None,
        exclude=[],
        skip_if_exists=[],
        tasks=[],
        jinja_extensions=[],
    )
    result = classify_file(p, cfg)
    assert result == FileJinjaClass.JINJA2_TEMPLATE


def test_classify_jinja_with_block(tmp_path: Path) -> None:
    p = tmp_path / "config.py.jinja"
    p.write_text("{% if use_redis %}import redis\n{% endif %}\n")
    from zenit.migrate.copier import CopierConfig

    cfg = CopierConfig(
        questions=[],
        subdirectory=None,
        exclude=[],
        skip_if_exists=[],
        tasks=[],
        jinja_extensions=[],
    )
    result = classify_file(p, cfg)
    assert result == FileJinjaClass.JINJA2_TEMPLATE


def test_classify_file_with_jinja_extension(tmp_path: Path) -> None:
    p = tmp_path / "main.py.jinja"
    p.write_text("{{ project_name }}")
    from zenit.migrate.copier import CopierConfig

    cfg = CopierConfig(
        questions=[],
        subdirectory=None,
        exclude=[],
        skip_if_exists=[],
        tasks=[],
        jinja_extensions=["jinja2.ext.i18n"],
    )
    result = classify_file(p, cfg)
    assert result == FileJinjaClass.UNTRANSLATABLE


def test_classify_excluded_file(tmp_path: Path) -> None:
    p = tmp_path / "secret.md"
    p.write_text("secret")

    cfg = CopierConfig(
        questions=[],
        subdirectory=None,
        exclude=["secret.md"],
        skip_if_exists=[],
        tasks=[],
        jinja_extensions=[],
    )
    result = classify_file(p, cfg)
    assert result == FileJinjaClass.EXCLUDED


# ── Extended Jinja2 environment (Phase 2, Step 2) ─────────────────────────────


def test_do_extension_loaded() -> None:
    """{% do %} tag is available on COPIER_ENV."""
    result = COPIER_ENV.from_string(
        "{% set items = [] %}{% do items.append(1) %}{{ items }}"
    ).render()
    assert result == "[1]"


def test_loopcontrols_extension_loaded() -> None:
    """{% break %} is available on COPIER_ENV."""
    result = COPIER_ENV.from_string(
        "{% for i in range(10) %}{% if i == 3 %}{% break %}{% endif %}{{ i }}{% endfor %}"
    ).render()
    assert result == "012"


def test_namespace_extension_loaded_and_works() -> None:
    """{% namespace %} renders its body as-is."""
    result = COPIER_ENV.from_string(
        "{% namespace mygroup %}hello{% endnamespace %}"
    ).render()
    assert "hello" in result


def test_unknown_extension_emits_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unknown extension in build_extended_env emits WARN."""
    config = CopierConfig(
        jinja_extensions=["nonexistent.module.Extension"],
    )
    warnings: list[str] = []
    monkeypatch.setattr(
        "zenit.migrate.copier.warn",
        lambda msg: warnings.append(msg),
    )
    build_extended_env(config)
    assert len(warnings) == 1
    assert "nonexistent.module.Extension" in warnings[0]


def test_shell_filter_emits_warning_and_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """shell() filter emits WARN and returns empty string."""
    warnings: list[str] = []
    monkeypatch.setattr(
        "zenit.migrate.copier.warn",
        lambda msg: warnings.append(msg),
    )
    result = _safe_shell_filter("echo hi")
    assert result == ""
    assert len(warnings) == 1
    assert "shell()" in warnings[0]


def test_make_secret_default_length() -> None:
    """make_secret() returns a 32-char alphanumeric string."""
    result = _make_secret()
    assert isinstance(result, str)
    assert len(result) == 32
    assert re.fullmatch(r"[a-zA-Z0-9]+", result)


def test_make_secret_custom_length() -> None:
    """make_secret(16) returns a 16-char alphanumeric string."""
    result = _make_secret(16)
    assert isinstance(result, str)
    assert len(result) == 16
    assert re.fullmatch(r"[a-zA-Z0-9]+", result)


def test_make_secret_is_available_as_global() -> None:
    """make_secret is registered as a global on COPIER_ENV."""
    result = COPIER_ENV.from_string("{{ make_secret() }}").render()
    assert isinstance(result, str)
    assert len(result) == 32


def test_make_secret_custom_length_in_template() -> None:
    """make_secret(8) works inside a template."""
    result = COPIER_ENV.from_string("{{ make_secret(8) }}").render()
    assert isinstance(result, str)
    assert len(result) == 8


def test_build_extended_env_preserves_standard_extensions() -> None:
    """build_extended_env includes standard extensions."""
    config = CopierConfig()
    env = build_extended_env(config)
    result = env.from_string(
        "{% set items = [] %}{% do items.append(42) %}{{ items }}"
    ).render()
    assert result == "[42]"
