"""Tests for normalise_pkg_name and resolve_dest_placeholder."""

from __future__ import annotations

import pytest

from zenit.core.pkg_name import normalise_pkg_name, resolve_dest_placeholder
from zenit.schema.exceptions import ZenitError

# ── normalise_pkg_name ─────────────────────────────────────────────────────────


def test_simple_hyphen() -> None:
    assert normalise_pkg_name("my-project") == "my_project"


def test_lowercasing() -> None:
    assert normalise_pkg_name("MyProject") == "myproject"


def test_dots() -> None:
    assert normalise_pkg_name("My.Project") == "my_project"


def test_spaces() -> None:
    assert normalise_pkg_name("Foo Bar") == "foo_bar"


def test_leading_trailing_special() -> None:
    assert normalise_pkg_name("-my-project-") == "my_project"


def test_idempotent() -> None:
    assert normalise_pkg_name("my_project") == "my_project"


def test_empty_string() -> None:
    assert normalise_pkg_name("") == ""


def test_multiple_special_chars() -> None:
    assert normalise_pkg_name("foo.!@#$bar") == "foo_____bar"


def test_mixed_case_with_hyphens() -> None:
    assert normalise_pkg_name("My-Cool-Project") == "my_cool_project"


# ── resolve_dest_placeholder ───────────────────────────────────────────────────


def test_resolve_replaces_pkg_name() -> None:
    assert (
        resolve_dest_placeholder("src/{{pkg_name}}/main.py", "myapp")
        == "src/myapp/main.py"
    )


def test_resolve_multiple_occurrences() -> None:
    assert (
        resolve_dest_placeholder("{{pkg_name}}/src/{{pkg_name}}/main.py", "myapp")
        == "myapp/src/myapp/main.py"
    )


def test_resolve_no_placeholder() -> None:
    assert resolve_dest_placeholder("src/main.py", "myapp") == "src/main.py"


def test_resolve_empty_string() -> None:
    assert resolve_dest_placeholder("", "myapp") == ""


def test_resolve_raises_on_unknown_placeholder() -> None:
    with pytest.raises(ZenitError, match="Unsupported placeholder '{{name}}'"):
        resolve_dest_placeholder("src/{{name}}/main.py", "myapp")


def test_resolve_raises_on_mixed_placeholders() -> None:
    """Only {{pkg_name}} is allowed even when mixed with unknown ones."""
    with pytest.raises(ZenitError, match="Unsupported placeholder '{{other}}'"):
        resolve_dest_placeholder("{{pkg_name}}/{{other}}/main.py", "myapp")


def test_resolve_pkg_name_with_underscores_in_context() -> None:
    """pkg_name can appear surrounded by other path components."""
    assert (
        resolve_dest_placeholder(
            "src/{{pkg_name}}/integrations/{{pkg_name}}_ext.py", "myapp"
        )
        == "src/myapp/integrations/myapp_ext.py"
    )


def test_resolve_does_not_affect_jinja2_delimiters() -> None:
    """(( ... )) should pass through unchanged (those are for template content)."""
    assert (
        resolve_dest_placeholder("src/{{pkg_name}}/(( name )).py", "myapp")
        == "src/myapp/(( name )).py"
    )
