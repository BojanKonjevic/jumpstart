"""Unit tests for zenit.core.handlers.locators.

Each locator is a pure function: libcst.Module → insertion index.
Tests cover success cases (parametrized), failure cases (LocatorError with
actionable messages), formatter resilience (libcst round-trip), and the
locate() dispatcher.
"""

from __future__ import annotations

import libcst as cst
import pytest

from zenit.core.handlers.locators import (
    LOCATOR_BEFORE_YIELD,
    LocatorError,
    after_last_class_attribute,
    after_last_import,
    after_statement_matching,
    at_module_end,
    before_return_in_function,
    before_yield_in_function,
    in_function_body,
    locate,
)

# ── helpers ───────────────────────────────────────────────────────────────────


def _parse(src: str) -> cst.Module:
    return cst.parse_module(src)


def _cst_normalised(src: str) -> str:
    """Return the libcst canonical form of *src* — the same normalisation
    that fingerprint_normalised applies. Used to generate formatter-resilient
    fixtures without a ruff subprocess dependency."""
    return cst.parse_module(src).code


# ── before_yield_in_function ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    "src, expected",
    [
        # Minimal: yield is the only statement — insert before index 0.
        ("async def lifespan():\n    yield\n", 0),
        # Yield after a pass — insert before index 1 (the yield).
        ("async def lifespan():\n    pass\n    yield\n", 1),
        # Yield after two statements — insert before index 2.
        ("async def lifespan():\n    x = 1\n    y = 2\n    yield\n", 2),
    ],
)
def test_before_yield_success(src: str, expected: int) -> None:
    assert before_yield_in_function(_parse(src), function="lifespan") == expected


def test_before_yield_formatter_resilient() -> None:
    src = "async def lifespan():\n    pass\n    yield\n"
    canonical = _cst_normalised(src)
    assert before_yield_in_function(_parse(canonical), function="lifespan") == 1


def test_before_yield_function_not_found() -> None:
    src = "async def startup():\n    yield\n"
    with pytest.raises(LocatorError, match="lifespan"):
        before_yield_in_function(_parse(src), function="lifespan")


def test_before_yield_no_yield_in_function() -> None:
    src = "async def lifespan():\n    pass\n"
    with pytest.raises(LocatorError, match="yield"):
        before_yield_in_function(_parse(src), function="lifespan")


# ── after_last_class_attribute ────────────────────────────────────────────────


@pytest.mark.parametrize(
    "src, expected",
    [
        # Two annotated attributes — insert after index 1 → index 2.
        ("class Settings:\n    name: str\n    age: int\n", 2),
        # Only a pass statement (no attributes) — insert at index 0.
        ("class Settings:\n    pass\n", 0),
        # Docstring then one attribute — insert at index 2.
        ('class Settings:\n    """doc"""\n    name: str\n', 2),
        # Docstring only, no attributes — insert at index 1 (after docstring).
        ('class Settings:\n    """doc"""\n    pass\n', 1),
        # Assignment-style attribute (not annotated).
        ("class Settings:\n    name = 'default'\n", 1),
    ],
)
def test_after_last_class_attribute_success(src: str, expected: int) -> None:
    assert after_last_class_attribute(_parse(src), class_name="Settings") == expected


def test_after_last_class_attribute_formatter_resilient() -> None:
    src = "class Settings:\n    name: str\n    age: int\n"
    canonical = _cst_normalised(src)
    assert after_last_class_attribute(_parse(canonical), class_name="Settings") == 2


def test_after_last_class_attribute_class_not_found() -> None:
    src = "class Config:\n    x: int\n"
    with pytest.raises(LocatorError, match="Settings"):
        after_last_class_attribute(_parse(src), class_name="Settings")


# ── after_last_import ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "src, expected",
    [
        # Two imports then a class — insert after index 1 → index 2.
        ("import os\nimport sys\nclass X: pass\n", 2),
        # No imports at all — insert at index 0.
        ("class X: pass\n", 0),
        # Module docstring then one import — insert at index 2.
        ('"""module doc"""\nimport os\n', 2),
        # Module docstring only, no imports — insert at index 1.
        ('"""module doc"""\nx = 1\n', 1),
        # from-import counts as an import.
        ("from pathlib import Path\nx = 1\n", 1),
    ],
)
def test_after_last_import_success(src: str, expected: int) -> None:
    assert after_last_import(_parse(src)) == expected


def test_after_last_import_formatter_resilient() -> None:
    src = "import os\nimport sys\nclass X: pass\n"
    canonical = _cst_normalised(src)
    assert after_last_import(_parse(canonical)) == 2


# ── after_statement_matching ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    "src, pattern, expected",
    [
        # Pattern matches the first statement — insert after index 0 → index 1.
        ("x = 1\ny = 2\n", "x = 1", 1),
        # Pattern matches the second statement — insert after index 1 → index 2.
        ("x = 1\ny = 2\nz = 3\n", "y = 2", 2),
        # Pattern is a regex.
        ("import os\nimport sys\n", r"import\s+sys", 2),
    ],
)
def test_after_statement_matching_success(
    src: str, pattern: str, expected: int
) -> None:
    assert after_statement_matching(_parse(src), pattern=pattern) == expected


def test_after_statement_matching_pattern_not_found() -> None:
    src = "x = 1\ny = 2\n"
    with pytest.raises(LocatorError, match="missing_anchor"):
        after_statement_matching(_parse(src), pattern="missing_anchor")


# ── before_return_in_function ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "src, expected",
    [
        # Statement then return — insert before return at index 1.
        ("def f():\n    x = 1\n    return x\n", 1),
        # No return — insert at end of body (index 1).
        ("def f():\n    pass\n", 1),
        # Return is the only statement — insert before index 0.
        ("def f():\n    return None\n", 0),
    ],
)
def test_before_return_success(src: str, expected: int) -> None:
    assert before_return_in_function(_parse(src), function="f") == expected


def test_before_return_formatter_resilient() -> None:
    src = "def f():\n    x = 1\n    return x\n"
    canonical = _cst_normalised(src)
    assert before_return_in_function(_parse(canonical), function="f") == 1


def test_before_return_function_not_found() -> None:
    src = "def g():\n    return 1\n"
    with pytest.raises(LocatorError, match="'f'"):
        before_return_in_function(_parse(src), function="f")


# ── at_module_end ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "src, expected",
    [
        ("x = 1\ny = 2\n", 2),
        ("", 0),
        ("import os\n", 1),
    ],
)
def test_at_module_end_success(src: str, expected: int) -> None:
    assert at_module_end(_parse(src)) == expected


# ── in_function_body ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "src, anchor, position, expected",
    [
        # After the anchor — index 1.
        ("def f():\n    x = 1\n    y = 2\n", "x = 1", "after", 1),
        # Before the anchor — index 0.
        ("def f():\n    x = 1\n    y = 2\n", "x = 1", "before", 0),
        # Anchor is the second statement; after → index 2.
        ("def f():\n    x = 1\n    y = 2\n    z = 3\n", "y = 2", "after", 2),
    ],
)
def test_in_function_body_success(
    src: str, anchor: str, position: str, expected: int
) -> None:
    assert (
        in_function_body(
            _parse(src), function="f", anchor_pattern=anchor, position=position
        )
        == expected
    )


def test_in_function_body_formatter_resilient() -> None:
    src = "def f():\n    x = 1\n    y = 2\n"
    canonical = _cst_normalised(src)
    assert (
        in_function_body(
            _parse(canonical), function="f", anchor_pattern="x = 1", position="after"
        )
        == 1
    )


def test_in_function_body_function_not_found() -> None:
    src = "def g():\n    x = 1\n"
    with pytest.raises(LocatorError, match="'f'"):
        in_function_body(_parse(src), function="f", anchor_pattern="x = 1")


def test_in_function_body_pattern_not_found() -> None:
    src = "def f():\n    x = 1\n"
    with pytest.raises(LocatorError, match="missing_pattern"):
        in_function_body(_parse(src), function="f", anchor_pattern="missing_pattern")


def test_in_function_body_invalid_position() -> None:
    src = "def f():\n    x = 1\n"
    with pytest.raises(LocatorError, match="position"):
        in_function_body(
            _parse(src), function="f", anchor_pattern="x = 1", position="middle"
        )


# ── locate() dispatcher ───────────────────────────────────────────────────────


def test_locate_dispatches_to_correct_locator() -> None:
    src = "async def lifespan():\n    yield\n"
    result = locate(_parse(src), LOCATOR_BEFORE_YIELD, {"function": "lifespan"})
    assert result == 0


def test_locate_unknown_name_raises_locator_error() -> None:
    src = "x = 1\n"
    with pytest.raises(LocatorError, match="nonexistent_locator"):
        locate(_parse(src), "nonexistent_locator", {})


def test_locate_error_message_lists_available_locators() -> None:
    src = "x = 1\n"
    with pytest.raises(LocatorError, match="Available"):
        locate(_parse(src), "typo_locator", {})
