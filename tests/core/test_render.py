"""Tests for zenit.render - Jinja2 environment configuration.

Includes a regression test for ``line_comment_prefix=None``, which must stay
set to prevent Jinja2's default ``##`` from silently eating comment lines in
generated Python files.
"""

from __future__ import annotations

import jinja2
import pytest

from zenit.core.render import build_render_vars, make_env

# ── Delimiter configuration ───────────────────────────────────────────────────


def test_variable_delimiters_are_double_parens():
    env = make_env()
    result = env.from_string("hello (( name ))!").render(name="world")
    assert result == "hello world!"


def test_block_delimiters_are_bracket_percent():
    env = make_env()
    tmpl = "[% if x %]yes[% else %]no[% endif %]"
    assert env.from_string(tmpl).render(x=True) == "yes"
    assert env.from_string(tmpl).render(x=False) == "no"


def test_default_jinja2_delimiters_are_NOT_active():
    """``{{ }}`` and ``{% %}`` must be treated as literal text, not Jinja2 syntax."""
    env = make_env()
    result = env.from_string("{{pkg_name}}").render(pkg_name="myapp")
    assert result == "{{pkg_name}}"


def test_default_block_delimiter_not_active():
    env = make_env()
    result = env.from_string("{% if True %}yes{% endif %}").render()
    assert result == "{% if True %}yes{% endif %}"


# ── line_comment_prefix regression ────────────────────────────────────────────


def test_hash_hash_is_NOT_a_line_comment():
    """REGRESSION: ``line_comment_prefix=None`` must be set.

    Jinja2's default ``line_comment_prefix`` is ``'##'``.  If it is
    accidentally removed, any Python line starting with ``##`` would be
    silently stripped from generated files - breaking double-hash comments in
    templates like Alembic scripts or docstrings.
    """
    env = make_env()
    template_text = "line1\n## this must survive\nline3\n"
    result = env.from_string(template_text).render()
    assert "## this must survive" in result, (
        "line_comment_prefix must be None - '##' lines are being stripped. "
        "Check that make_env() sets line_comment_prefix=None."
    )


def test_single_hash_is_never_a_comment():
    env = make_env()
    result = env.from_string("# regular comment\n").render()
    assert "# regular comment" in result


def test_triple_hash_survives_too():
    env = make_env()
    result = env.from_string("### heading\n").render()
    assert "### heading" in result


# ── keep_trailing_newline ─────────────────────────────────────────────────────


def test_trailing_newline_is_preserved():
    env = make_env()
    result = env.from_string("content\n").render()
    assert result.endswith("\n")


def test_multiple_trailing_newlines_preserved():
    env = make_env()
    result = env.from_string("content\n\n").render()
    assert result.endswith("\n\n")


# ── loader_path ───────────────────────────────────────────────────────────────


def test_env_with_loader_path_loads_templates(tmp_path):
    (tmp_path / "hello.txt.j2").write_text("Hi (( name ))!\n")
    env = make_env(tmp_path)
    result = env.get_template("hello.txt.j2").render(name="Bojan")
    assert result == "Hi Bojan!\n"


def test_env_without_loader_path_renders_strings():
    env = make_env()
    result = env.from_string("(( x )) + (( y ))").render(x=1, y=2)
    assert result == "1 + 2"


def test_env_without_loader_path_cannot_load_files():
    env = make_env()
    with pytest.raises(jinja2.TemplateNotFound):
        env.get_template("nonexistent.j2")


def test_loader_path_as_none_falls_back_to_base_loader():
    env = make_env(None)
    result = env.from_string("(( val ))").render(val="ok")
    assert result == "ok"


# ── for-loop in blocks ────────────────────────────────────────────────────────


def test_for_loop_with_custom_delimiters():
    env = make_env()
    tmpl = "[% for item in items %](( item ))\n[% endfor %]"
    result = env.from_string(tmpl).render(items=["a", "b", "c"])
    assert result == "a\nb\nc\n"


# ── raw block ─────────────────────────────────────────────────────────────────


def test_raw_block_passes_through_unchanged():
    """``[% raw %] … [% endraw %]`` must work for alembic.ini templates."""
    env = make_env()
    tmpl = "[% raw %]%(levelname)s [%(name)s][% endraw %]"
    result = env.from_string(tmpl).render()
    assert result == "%(levelname)s [%(name)s]"


# ── filter / default ──────────────────────────────────────────────────────────


def test_default_filter_works():
    env = make_env()
    result = env.from_string("(( val | default('fallback') ))").render()
    assert result == "fallback"


# ── Two envs are independent ──────────────────────────────────────────────────


def test_two_envs_with_different_loader_paths_are_independent(tmp_path):
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    (dir_a / "tmpl.txt").write_text("from A: (( x ))")
    (dir_b / "tmpl.txt").write_text("from B: (( x ))")

    env_a = make_env(dir_a)
    env_b = make_env(dir_b)

    assert env_a.get_template("tmpl.txt").render(x="hello") == "from A: hello"
    assert env_b.get_template("tmpl.txt").render(x="hello") == "from B: hello"


# ── build_render_vars ──────────────────────────────────────────────────────────


def test_build_render_vars_includes_deps_and_dev_deps():
    result = build_render_vars(
        name="myapp",
        pkg_name="myapp",
        template="blank",
        deps=["fastapi", "redis"],
        dev_deps=["pytest", "mypy"],
    )
    assert result["deps"] == ["fastapi", "redis"]
    assert result["dev_deps"] == ["pytest", "mypy"]


def test_build_render_vars_defaults_deps_to_empty():
    result = build_render_vars(name="myapp", pkg_name="myapp", template="blank")
    assert result["deps"] == []
    assert result["dev_deps"] == []


def test_build_render_vars_deps_are_renderable_in_template():
    env = make_env()
    vars = build_render_vars(
        name="myapp",
        pkg_name="myapp",
        template="blank",
        deps=["fastapi", "redis>=5"],
    )
    tmpl = "[% for dep in deps %](( dep ))\n[% endfor %]"
    result = env.from_string(tmpl).render(**vars)
    assert result == "fastapi\nredis>=5\n"


def test_build_render_vars_dev_deps_are_renderable_in_template():
    env = make_env()
    vars = build_render_vars(
        name="myapp",
        pkg_name="myapp",
        template="blank",
        dev_deps=["pytest>=8", "mypy"],
    )
    tmpl = "[% for dep in dev_deps %](( dep ))\n[% endfor %]"
    result = env.from_string(tmpl).render(**vars)
    assert result == "pytest>=8\nmypy\n"
