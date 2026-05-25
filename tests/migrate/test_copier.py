"""Tests for Copier YAML parsing, question classification, and delimiter swap."""

from pathlib import Path

import pytest
import yaml

from zenit.migrate.copier import (
    FileJinjaClass,
    QuestionClass,
    QuestionType,
    classify_file,
    classify_questions,
    parse_copier_yml,
    translate_delimiters,
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
    from zenit.migrate.copier import CopierConfig

    cfg = CopierConfig(
        questions=[],
        subdirectory=None,
        exclude=["secret.md"],
        skip_if_exists=[],
        tasks=[],
        jinja_extensions=[],
    )
    result = classify_file(p, cfg)
    assert result == FileJinjaClass.STATIC


# ── translate_delimiters ───────────────────────────────────────────────────────


def test_translate_variable() -> None:
    result = translate_delimiters("{{ project_name }}")
    assert result == "((project_name))"


def test_translate_block_if() -> None:
    result = translate_delimiters("{% if use_redis %}content{% endif %}")
    assert result == "[% if use_redis %]content[% endif %]"


def test_translate_block_for() -> None:
    result = translate_delimiters("{% for item in items %}{{ item }}{% endfor %}")
    assert result == "[% for item in items %]((item))[% endfor %]"


def test_translate_raw_block() -> None:
    result = translate_delimiters("before{% raw %}{{ literal }}{% endraw %}after")
    assert result == "before{{ literal }}after"


def test_translate_comment_dropped() -> None:
    result = translate_delimiters("before{# comment #}after")
    assert result == "beforeafter"


def test_translate_mixed_content() -> None:
    result = translate_delimiters(
        "{% if x %}{{ a }}{% endif %}{# c #}{% raw %}{{ b }}{% endraw %}"
    )
    assert result == "[% if x %]((a))[% endif %]{{ b }}"


def test_translate_invalid_template_raises() -> None:
    """Unclosed block should raise TemplateSyntaxError."""
    import jinja2

    with pytest.raises(jinja2.exceptions.TemplateSyntaxError):
        translate_delimiters("{% if x %}")


def test_translate_nested_blocks() -> None:
    result = translate_delimiters(
        "{% for u in users %}{{ u.name }}{% if u.active %}(active){% endif %}{% endfor %}"
    )
    assert result == (
        "[% for u in users %]((u.name))[% if u . active %](active)[% endif %][% endfor %]"
    )


def test_translate_line_comment_ignored() -> None:
    """Zenit disables line comments, but Copier's ## should not break translation."""
    result = translate_delimiters("before\n## this is a comment\n{{ var }}")
    assert "((var))" in result
    assert "## this is a comment" in result


def test_translate_empty_content() -> None:
    assert translate_delimiters("") == ""


def test_translate_no_jinja() -> None:
    text = "plain text no jinja"
    assert translate_delimiters(text) == text


def test_translate_multiple_lines() -> None:
    text = """line1
{{ var1 }}
{% if cond %}
{{ var2 }}
{% endif %}
"""
    result = translate_delimiters(text)
    assert "((var1))" in result
    assert "[% if cond %]" in result or "[%if cond%]" in result
    assert "[% endif %]" in result or "[%endif%]" in result
    assert "((var2))" in result
