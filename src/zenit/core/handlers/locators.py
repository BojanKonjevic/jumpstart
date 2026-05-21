"""Structural locator library for Python file injection.

Each locator is a **pure function** that receives a ``libcst.Module`` and
keyword arguments, and returns the integer body-index at which new statements
should be inserted.  All locators raise ``LocatorError`` with an actionable
message on failure — never a bare ``IndexError`` or ``AttributeError``.

Locator contract
----------------
- Return value is the index *before which* the new code will be inserted
  into the relevant sequence (module body or function/class body).
- Pure: no side effects, no I/O.
- Raise ``LocatorError`` (never a generic exception) with a message that
  tells the user exactly what to look for and why it failed.

Registered locators
-------------------
before_yield_in_function   — before the ``yield`` in an async generator function
after_last_class_attribute — after the last non-comment attribute in a class body
after_last_import          — after the last import statement in the module
after_statement_matching   — after the first statement matching a regex
before_return_in_function  — before the first ``return`` in a named function
at_module_end              — append at end of module body
at_file_end                — (non-Python files) no-op sentinel; only Python files use locators
in_function_body           — inside a named function, before/after an anchor statement
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

import libcst as cst

# ── Public exception ──────────────────────────────────────────────────────────


class LocatorError(Exception):
    """Raised when a locator cannot find its target in the parsed module."""


# ── Dispatcher ────────────────────────────────────────────────────────────────


def locate(module: cst.Module, spec_name: str, spec_args: dict[str, Any]) -> int:
    """Dispatch to the named locator and return the insertion index.

    Parameters
    ----------
    module:
        Parsed ``libcst.Module``.
    spec_name:
        Name of the locator function (must be in ``_REGISTRY``).
    spec_args:
        Keyword arguments forwarded to the locator.
    """
    fn = _REGISTRY.get(spec_name)
    if fn is None:
        raise LocatorError(
            f"Unknown locator '{spec_name}'. Available: {', '.join(sorted(_REGISTRY))}."
        )
    return fn(module, **spec_args)


# ── Locator implementations ───────────────────────────────────────────────────


def before_yield_in_function(module: cst.Module, *, function: str) -> int:
    """Return the body index just before the ``yield`` statement in *function*.

    The new code will be inserted before the yield, so it runs during the
    lifespan startup phase.
    """
    for node in module.body:
        if isinstance(node, cst.FunctionDef) and node.name.value == function:
            body = node.body
            if not isinstance(body, cst.IndentedBlock):
                raise LocatorError(
                    f"Function '{function}' has an unexpected body type "
                    f"({type(body).__name__}). Cannot locate yield."
                )
            for i, stmt in enumerate(body.body):
                if _contains_yield(stmt):
                    return i
            raise LocatorError(
                f"Could not find a yield statement in function '{function}'.\n"
                f"Has the function been removed, renamed, or converted from an "
                f"async generator to a regular function?"
            )
    raise LocatorError(
        f"Could not find function '{function}' in the module.\n"
        f"Has the function been removed or renamed?"
    )


def after_last_class_attribute(module: cst.Module, *, class_name: str) -> int:
    """Return the index after the last simple attribute in *class_name*'s body.

    A 'simple attribute' is any ``SimpleStatementLine`` that is not a
    docstring and is not a bare ellipsis / pass.  If the class has no
    attributes, returns 1 (after the docstring if present, else at position 0
    so the class body doesn't start empty).
    """
    for node in module.body:
        if isinstance(node, cst.ClassDef) and node.name.value == class_name:
            body = node.body
            if not isinstance(body, cst.IndentedBlock):
                raise LocatorError(f"Class '{class_name}' has an unexpected body type.")
            stmts = body.body
            last_attr_idx = -1
            for i, stmt in enumerate(stmts):
                if _is_class_attribute(stmt):
                    last_attr_idx = i
            if last_attr_idx == -1:
                # No attributes found; insert at 1 (after docstring if present)
                if stmts and _is_docstring(stmts[0]):
                    return 1
                return 0
            return last_attr_idx + 1
    raise LocatorError(
        f"Could not find class '{class_name}' in the module.\n"
        f"Has the class been removed or renamed?"
    )


def after_last_import(module: cst.Module) -> int:
    """Return the index after the last import statement at module level."""
    last_import_idx: int = -1
    for i, stmt in enumerate(module.body):
        if _is_import(stmt):
            last_import_idx = i
    if last_import_idx == -1:
        # No imports found — insert at the start (after module docstring if any)
        if module.body and _is_docstring(module.body[0]):
            return 1
        return 0
    return last_import_idx + 1


def after_statement_matching(module: cst.Module, *, pattern: str) -> int:
    """Return the index after the first statement whose source matches *pattern*.

    *pattern* is a regular expression matched against the full source text of
    each top-level statement.
    """
    compiled = re.compile(pattern)
    for i, stmt in enumerate(module.body):
        src = module.code_for_node(stmt)
        if compiled.search(src):
            return i + 1
    raise LocatorError(
        f"No top-level statement matches pattern {pattern!r}.\n"
        f"The expected anchor statement may have been removed or reformatted."
    )


def before_return_in_function(module: cst.Module, *, function: str) -> int:
    """Return the body index just before the first ``return`` in *function*."""
    for node in module.body:
        if isinstance(node, cst.FunctionDef) and node.name.value == function:
            body = node.body
            if not isinstance(body, cst.IndentedBlock):
                raise LocatorError(
                    f"Function '{function}' has an unexpected body type."
                )
            for i, stmt in enumerate(body.body):
                if _contains_return(stmt):
                    return i
            # No explicit return — insert at end
            return len(body.body)
    raise LocatorError(
        f"Could not find function '{function}' in the module.\n"
        f"Has the function been removed or renamed?"
    )


def at_module_end(module: cst.Module) -> int:
    """Return the index that appends at the end of the module body."""
    return len(module.body)


def at_file_end(module: cst.Module) -> int:  # noqa: ARG001
    """Alias for at_module_end — used as the locator name for non-Python append targets.

    For non-Python handlers (.env, justfile, etc.) the locator is ignored;
    this function exists only so LocatorSpec validation passes.
    """
    return len(module.body)


def in_function_body(
    module: cst.Module,
    *,
    function: str,
    anchor_pattern: str,
    position: str = "after",
) -> int:
    """Return the index before/after the first statement matching *anchor_pattern* in *function*.

    Parameters
    ----------
    function:
        Name of the function to search inside.
    anchor_pattern:
        Regex matched against each statement's source text.
    position:
        ``"before"`` or ``"after"`` the matched statement.
    """
    if position not in ("before", "after"):
        raise LocatorError(f"position must be 'before' or 'after', got {position!r}.")
    compiled = re.compile(anchor_pattern)
    for node in module.body:
        if isinstance(node, cst.FunctionDef) and node.name.value == function:
            body = node.body
            if not isinstance(body, cst.IndentedBlock):
                raise LocatorError(
                    f"Function '{function}' has an unexpected body type."
                )
            for i, stmt in enumerate(body.body):
                src = module.code_for_node(stmt)
                if compiled.search(src):
                    return i if position == "before" else i + 1
            raise LocatorError(
                f"No statement in '{function}' matches pattern {anchor_pattern!r}."
            )
    raise LocatorError(
        f"Could not find function '{function}' in the module.\n"
        f"Has the function been removed or renamed?"
    )


# ── Private helpers ───────────────────────────────────────────────────────────


def _contains_yield(stmt: cst.BaseStatement) -> bool:
    """Return True if *stmt* is or contains a yield expression."""

    class YieldFinder(cst.CSTVisitor):
        found: bool = False

        def visit_Yield(self, node: cst.Yield) -> None:
            self.found = True

    finder = YieldFinder()
    stmt.visit(finder)
    return finder.found


def _contains_return(stmt: cst.BaseStatement) -> bool:
    """Return True if *stmt* is a return statement."""
    if isinstance(stmt, cst.SimpleStatementLine):
        return any(isinstance(s, cst.Return) for s in stmt.body)
    return False


def _is_import(stmt: cst.BaseStatement) -> bool:
    """Return True if *stmt* is an import or from-import statement."""
    if isinstance(stmt, cst.SimpleStatementLine):
        return any(isinstance(s, (cst.Import, cst.ImportFrom)) for s in stmt.body)
    return False


def _is_class_attribute(stmt: cst.BaseStatement) -> bool:
    """Return True if *stmt* is a class field assignment or annotation."""
    if not isinstance(stmt, cst.SimpleStatementLine):
        return False
    if len(stmt.body) != 1:
        return False
    return isinstance(stmt.body[0], (cst.Assign, cst.AnnAssign))


def _is_docstring(stmt: cst.BaseStatement) -> bool:
    """Return True if *stmt* is a module/class/function docstring."""
    if not isinstance(stmt, cst.SimpleStatementLine):
        return False
    if len(stmt.body) != 1:
        return False
    inner = stmt.body[0]
    return isinstance(inner, cst.Expr) and isinstance(
        inner.value, (cst.SimpleString, cst.FormattedString, cst.ConcatenatedString)
    )


# ── Registry ──────────────────────────────────────────────────────────────────


_REGISTRY: dict[str, Callable[..., int]] = {
    "before_yield_in_function": before_yield_in_function,
    "after_last_class_attribute": after_last_class_attribute,
    "after_last_import": after_last_import,
    "after_statement_matching": after_statement_matching,
    "before_return_in_function": before_return_in_function,
    "at_module_end": at_module_end,
    "at_file_end": at_file_end,
    "in_function_body": in_function_body,
}
