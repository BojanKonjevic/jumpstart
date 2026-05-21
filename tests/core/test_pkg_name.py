"""Tests for normalise_pkg_name."""

from __future__ import annotations

from zenit.core.pkg_name import normalise_pkg_name


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
