from __future__ import annotations

import sys
from collections.abc import Sequence as _Seq
from difflib import SequenceMatcher
from pathlib import Path
from typing import TYPE_CHECKING

import libcst as cst

from zenit.core.handlers.base import FileHandler
from zenit.core.handlers.locators import LocatorError, locate
from zenit.core.manifest import _normalise as _manifest_normalise
from zenit.core.manifest import fingerprint as _fingerprint
from zenit.schema.exceptions import ZenitError

if TYPE_CHECKING:
    from zenit.schema.models import ManifestBlock


def _locate_line(
    module: cst.Module,
    locator_name: str,
    locator_args: dict[str, object],
    insert_index: int,
) -> int:
    """Convert a CST body-index to a 0-based line index for text-level splicing.

    locate() returns an index into a body sequence (module.body,
    ClassDef.body.body, FunctionDef.body.body).  This function uses
    PositionProvider to find the actual line in the source file.

    Invariant: source.splitlines(keepends=True)[:result] contains exactly the
    lines before the insertion point.
    """
    from libcst.metadata import MetadataWrapper, PositionProvider

    wrapper = MetadataWrapper(module, unsafe_skip_copy=True)
    positions = wrapper.resolve(PositionProvider)

    def _split_for(body: _Seq[cst.CSTNode], idx: int) -> int:
        # Insert BEFORE body[idx].
        # Positions are 1-based; splitlines() is 0-based.
        if idx < len(body):
            if idx > 0:
                # Use end of previous element so we don't land between a
                # decorator and its function/class definition.
                return positions[body[idx - 1]].end.line
            # idx == 0 → insert before the first element.
            # For function bodies (before_yield etc.) line 0 is wrong — we
            # need the global line of the first body statement.
            return positions[body[0]].start.line - 1
        # Past end → insert after the last statement.
        if body:
            # end.line is 1-based, so it doubles as the 0-based "after" index.
            return positions[body[-1]].end.line
        return 0

    if locator_name in (
        "after_last_import",
        "after_statement_matching",
        "at_module_end",
        "at_file_end",
    ):
        return _split_for(module.body, insert_index)

    if locator_name == "after_last_class_attribute":
        class_name = str(locator_args.get("class_name", ""))
        for node in module.body:
            if isinstance(node, cst.ClassDef) and node.name.value == class_name:
                return _split_for(node.body.body, insert_index)
        raise InjectionError(
            f"_locate_line: class '{class_name}' not found in module. "
            "Cannot convert CST index to line number."
        )

    if locator_name in (
        "before_yield_in_function",
        "before_return_in_function",
        "in_function_body",
    ):
        fn_name = str(locator_args.get("function", ""))
        for node in module.body:
            if isinstance(node, cst.FunctionDef) and node.name.value == fn_name:
                return _split_for(node.body.body, insert_index)
        raise InjectionError(
            f"_locate_line: function '{fn_name}' not found in module. "
            f"Cannot convert CST index to line number. "
            f"Has the function been removed or renamed?"
        )

    # Unknown locator — fail loudly so developers add it to the dispatch table.
    raise InjectionError(
        f"Locator '{locator_name}' is not supported by _locate_line. "
        f"Add it to the dispatch table in python_handler.py."
    )


# ── Constants ────────────────────────────────────────────────────────────────

FUZZY_REMOVAL_THRESHOLD: float = 0.85
FUZZY_WINDOW_LINES: int = 20


# ── Exceptions ────────────────────────────────────────────────────────────────


class InjectionError(ZenitError):
    """Raised when a structural injection cannot be completed."""


class RemovalError(ZenitError):
    """Raised when an injected block cannot be located for removal."""


# ── Normalisation helpers (delegated to manifest.py) ─────────────────────────


def _normalise_for_fuzzy(source: str) -> str:
    """Produce a normalised string suitable for fuzzy-match comparison.

    Uses the same normalisation as manifest.fingerprint() so that fuzzy
    scoring is consistent with the stored fingerprint_normalised values.
    Delegates to manifest._normalise via the round-trip already done there.
    We call _fingerprint on a best-effort basis — if libcst cannot parse
    the fragment (e.g. it is not valid Python), fall back to rstrip-only.
    """
    try:
        module = cst.parse_module(source)
        return _manifest_normalise(module.code)
    except Exception:
        lines = [ln.rstrip() for ln in source.splitlines()]
        return "\n".join(lines)


# ── Core apply / remove ───────────────────────────────────────────────────────


def apply(
    file: Path,
    content: str,
    locator_name: str,
    locator_args: dict[str, object],
) -> tuple[str, int, int]:
    source = file.read_text(encoding="utf-8")
    module = cst.parse_module(source)
    try:
        insert_index = locate(module, locator_name, locator_args)
    except LocatorError as exc:
        raise InjectionError(
            f"Cannot inject at '{locator_name}' in {file}.\n  Reason: {exc}"
        ) from exc

    # Convert CST body-index → source-file line index.
    line_number = _locate_line(module, locator_name, locator_args, insert_index)

    lines = source.splitlines(keepends=True)
    content_lines = content.splitlines(keepends=True)
    if content_lines and not content_lines[-1].endswith("\n"):
        content_lines[-1] += "\n"

    new_lines = lines[:line_number] + content_lines + lines[line_number:]
    new_source = "".join(new_lines)

    start_line = line_number + 1  # 1-based
    end_line = line_number + len(content_lines)

    file.write_text(new_source, encoding="utf-8")
    return new_source, start_line, end_line


def remove(
    file: Path,
    block: ManifestBlock,
) -> None:
    """Remove a previously injected block from *file*.

    Stages:
        A — exact fingerprint match on recorded lines.
        B — normalised fingerprint match (formatter-resilient).
        C — fuzzy match within FUZZY_WINDOW_LINES of recorded position.
        D — raise RemovalError with actionable instructions.
    """
    source = file.read_text(encoding="utf-8")
    lines = source.splitlines(keepends=True)

    start_str, end_str = block.lines.split("-")
    rec_start = int(start_str) - 1  # 0-based inclusive
    rec_end = int(end_str) - 1  # 0-based inclusive

    def _extract(s: int, e: int) -> str:
        return "".join(lines[s : e + 1])

    # ── Stage A: exact fingerprint ───────────────────────────────────────────
    if 0 <= rec_start < len(lines) and rec_end < len(lines):
        candidate = _extract(rec_start, rec_end)
        fp, _ = _fingerprint(candidate)
        if fp == block.fingerprint:
            _remove_lines(file, lines, rec_start, rec_end)
            return

    # ── Stage B: normalised fingerprint ─────────────────────────────────────
    if 0 <= rec_start < len(lines) and rec_end < len(lines):
        candidate = _extract(rec_start, rec_end)
        _, fp_norm = _fingerprint(candidate)
        if fp_norm == block.fingerprint_normalised:
            _remove_lines(file, lines, rec_start, rec_end)
            return

    # ── Stage C: fuzzy match in window ──────────────────────────────────────
    block_len = rec_end - rec_start + 1
    window_start = max(0, rec_start - FUZZY_WINDOW_LINES)
    window_end = min(len(lines) - 1, rec_end + FUZZY_WINDOW_LINES)

    ref_start = max(0, min(rec_start, len(lines) - 1))
    ref_end = max(0, min(rec_end, len(lines) - 1))
    ref_text = "".join(lines[ref_start : ref_end + 1])
    norm_ref = _normalise_for_fuzzy(ref_text) if ref_text else ""

    best_ratio = 0.0
    best_start = -1

    for s in range(window_start, window_end + 1):
        e = s + block_len - 1
        if e > len(lines) - 1:
            break
        candidate = _normalise_for_fuzzy(_extract(s, e))
        ratio = SequenceMatcher(None, norm_ref, candidate).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_start = s

    if best_ratio >= FUZZY_REMOVAL_THRESHOLD and best_start >= 0:
        best_end = best_start + block_len - 1
        print(
            f"Warning: fuzzy removal matched '{block.point}' in {file} "
            f"at lines {best_start + 1}-{best_end + 1} "
            f"(similarity {best_ratio:.0%}). Block may have been reformatted.",
            file=sys.stderr,
        )
        _remove_lines(file, lines, best_start, best_end)
        return

    # ── Stage D: unrecoverable ───────────────────────────────────────────────
    raise RemovalError(
        f"Could not remove '{block.point}' injection for addon '{block.addon}'.\n"
        f"  File: {file}\n"
        f"  Expected block at lines {block.lines} (fingerprint {block.fingerprint}), "
        f"but the code has changed beyond the fuzzy-match threshold.\n"
        f"  Manual steps:\n"
        f"    - Open {file}\n"
        f"    - Find the code added by the '{block.addon}' addon for point '{block.point}'\n"
        f"    - Remove it, then run: zenit doctor"
    )


def _remove_lines(
    file: Path,
    lines: list[str],
    start: int,
    end: int,
) -> None:
    """Delete lines[start:end+1] from *file*, cleaning up surrounding blank lines."""
    new_lines = lines[:start] + lines[end + 1 :]
    cleaned = _collapse_blank_lines(new_lines)

    file.write_text("".join(cleaned), encoding="utf-8")


def _collapse_blank_lines(lines: list[str]) -> list[str]:
    """Collapse runs of 3+ consecutive blank lines to exactly 2.

    Matches the normalisation contract in manifest._normalise():
      'Collapse runs of 3+ consecutive newlines to exactly two newlines.'
    """
    cleaned: list[str] = []
    blank_run = 0

    for ln in lines:
        is_blank = ln.strip() == ""
        if is_blank:
            blank_run += 1
            if blank_run <= 2:
                cleaned.append(ln)
            # else: drop the line (3rd+ consecutive blank)
        else:
            blank_run = 0
            cleaned.append(ln)

    return cleaned


class PythonHandler(FileHandler):
    def can_handle(self, path: Path) -> bool:
        return path.suffix == ".py"

    def apply(
        self,
        file: Path,
        content: str,
        locator_name: str,
        locator_args: dict[str, object],
    ) -> tuple[str, int, int]:
        return apply(file, content, locator_name, locator_args)

    def remove(self, file: Path, block: ManifestBlock) -> None:
        remove(file, block)
