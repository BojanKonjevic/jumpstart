"""Shared rendering helpers for TUI prompts."""

from __future__ import annotations

import sys
from collections.abc import Callable

from zenit.cli.ui import BOLD, CYAN, DIM, GREEN, MAGENTA, RESET, YELLOW, abort, warn

from ._keys import read_key

# ── ANSI escape sequences ─────────────────────────────────────────────────────

_HIDE_CURSOR = "\033[?25l"
_SHOW_CURSOR = "\033[?25h"
_CLEAR_LINE = "\033[2K\r"
_UP = "\033[A"


def hide_cursor() -> None:
    sys.stdout.write(_HIDE_CURSOR)
    sys.stdout.flush()


def show_cursor() -> None:
    sys.stdout.write(_SHOW_CURSOR)
    sys.stdout.flush()


def clear_lines(n: int) -> None:
    for _ in range(n):
        sys.stdout.write(_CLEAR_LINE)
        sys.stdout.write(_UP)
    sys.stdout.write(_CLEAR_LINE)
    sys.stdout.flush()


def reserve_lines(n: int) -> None:
    """Print blank lines to ensure the menu has room without causing scroll during redraw."""
    sys.stdout.write("\n" * n)
    sys.stdout.flush()


# ── Constants ─────────────────────────────────────────────────────────────────

ARROW = f"{MAGENTA}›{RESET}"
CHECK = f"{GREEN}●{RESET}"
EMPTY = f"{DIM}○{RESET}"
LOCKED = f"{YELLOW}●{RESET}"
CROSS = f"{DIM}—{RESET}"

LABEL_WIDTH = 20
DESC_INDENT = "  "

TEMPLATES: list[tuple[str, str]] = [
    ("blank", "dev tools only  (pytest, ruff, mypy)"),
    ("fastapi", "FastAPI web framework skeleton"),
]

TEMPLATE_REQUIRES: dict[str, list[str]] = {}


# ── Search ─────────────────────────────────────────────────────────────────────


def filter_indices(
    items: list[tuple[str, str]],
    query: str,
) -> list[int]:
    """Return indices of *items* whose name or description matches *query* (case‑insensitive).

    Returns all indices when query is empty.
    """
    if not query:
        return list(range(len(items)))
    q = query.lower()
    return [
        i
        for i, (name, desc) in enumerate(items)
        if q in name.lower() or q in desc.lower()
    ]


# ── Footer lines ──────────────────────────────────────────────────────────────

_FOOTER_SINGLE = f"  {DIM}↑↓ navigate · enter select · type to search{RESET}"
_FOOTER_SINGLE_SEARCH = f"  {DIM}↑↓ navigate · enter confirm · esc clear{RESET}"
_FOOTER_MULTI = (
    f"  {DIM}↑↓ navigate · space toggle · enter confirm · type to search{RESET}"
)
_FOOTER_MULTI_SEARCH = (
    f"  {DIM}↑↓ navigate · space toggle · enter confirm · esc clear{RESET}"
)


# ── Renderers ─────────────────────────────────────────────────────────────────


def render_single(
    items: list[tuple[str, str]],
    cursor: int,
    *,
    default_name: str | None = None,
    unavailable: set[int] | None = None,
    full_items: list[tuple[str, str, list[str]]] | None = None,
    flash: str = "",
    context: str = "add",
    filtered_indices: list[int] | None = None,
    search_query: str = "",
) -> int:
    """Render a single-select TUI list. Returns the number of lines written."""
    unavailable = unavailable or set()
    filtered = (
        filtered_indices if filtered_indices is not None else list(range(len(items)))
    )
    lines = 0

    for idx, orig_i in enumerate(filtered):
        name, desc = items[orig_i]
        is_unavailable = orig_i in unavailable
        is_cursor = idx == cursor

        prefix = f"  {ARROW} " if is_cursor else "     "

        if is_unavailable:
            tick = f"{CROSS}  "
        elif is_cursor:
            tick = f"{CHECK}  "
        else:
            tick = f"{EMPTY}  "

        padded_name = f"{name:<{LABEL_WIDTH}}"
        if is_unavailable:
            padded_label = f"{DIM}{padded_name}{RESET}"
        elif is_cursor:
            padded_label = f"{CYAN}{BOLD}{padded_name}{RESET}"
        else:
            padded_label = padded_name

        desc_text = f"{DIM}{desc}{RESET}"

        extra = ""
        if not is_cursor and name == default_name:
            extra = f"  {DIM}(default){RESET}"
        elif is_unavailable and full_items and orig_i < len(full_items):
            reqs = full_items[orig_i][2]
            if reqs:
                template_blocks = [r for r in reqs if r.startswith("__template__")]
                addon_deps = [r for r in reqs if not r.startswith("__template__")]
                parts = []
                if addon_deps:
                    label = "required by" if context == "remove" else "needs"
                    parts.append(f"{label} {', '.join(addon_deps)}")
                if template_blocks:
                    tmpl = template_blocks[0].replace("__template__", "")
                    parts.append(f"required by {tmpl} template")
                if parts:
                    extra = f"  {DIM}({', '.join(parts)}){RESET}"

        sys.stdout.write(
            f"{prefix}{tick}{padded_label}{DESC_INDENT}{desc_text}{extra}\n"
        )
        lines += 1

    if not filtered:
        sys.stdout.write(f"  {DIM}No matches{RESET}\n")
        lines += 1

    if flash:
        sys.stdout.write(f"\n  {YELLOW}⚠  {flash}{RESET}\n")
        lines += 2
    elif search_query:
        sys.stdout.write(f"\n  {DIM}Search: {search_query}{RESET}\n")
        sys.stdout.write(f"  {_FOOTER_SINGLE_SEARCH}\n")
        lines += 3
    else:
        sys.stdout.write(f"\n  {_FOOTER_SINGLE}\n")
        lines += 2
    sys.stdout.flush()
    return lines


# ── TUI loop ──────────────────────────────────────────────────────────────────

_DONE = object()


def run_tui(
    render: Callable[[], int],
    on_key: Callable[[str], object],
) -> None:
    """Generic TUI loop: render → read key → call handler → clear → repeat.

    on_key should return _DONE to exit the loop, anything else to continue.
    Handles ctrl-c and cursor show/hide.
    """

    hide_cursor()
    rendered = render()
    try:
        while True:
            key = read_key()
            result = on_key(key)
            if result is _DONE:
                break
            clear_lines(rendered)
            rendered = render()
    finally:
        show_cursor()


# ── Fallback (non-tty) ────────────────────────────────────────────────────────


def run_fallback(
    items: list[tuple[str, str]],
    *,
    default_name: str | None = None,
    unavailable: set[int] | None = None,
    full_items: list[tuple[str, str, list[str]]] | None = None,
    prompt_text: str = "Selection",
    context: str = "add",
) -> int | None:
    """Fallback numbered-list picker for non-tty environments.

    Returns the selected index, or None if the user cancels.
    """

    unavailable = unavailable or set()

    for i, (name, desc) in enumerate(items, 1):
        is_unavailable = (i - 1) in unavailable
        markers = []
        if is_unavailable and full_items:
            reqs = full_items[i - 1][2]
            if reqs:
                template_blocks = [r for r in reqs if r.startswith("__template__")]
                addon_deps = [r for r in reqs if not r.startswith("__template__")]
                if addon_deps:
                    label = "required by" if context == "remove" else "needs"
                    markers.append(f"{label} {', '.join(addon_deps)}")
                if template_blocks:
                    tmpl = template_blocks[0].replace("__template__", "")
                    markers.append(f"required by {tmpl} template")
        if name == default_name:
            markers.append("default")
        suffix = f"  {DIM}({', '.join(markers)}){RESET}" if markers else ""
        print(f"    {CYAN}{i}){RESET} {name:<18} {DIM}—{RESET} {desc}{suffix}")
    print()

    hint = f"1-{len(items)}"
    if default_name:
        hint += f", or enter for {default_name}"
    else:
        hint += ", or enter to cancel"

    while True:
        try:
            raw = input(f"  {prompt_text} [{hint}]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            abort()

        if not raw:
            if default_name:
                for i, (name, _) in enumerate(items):
                    if name == default_name:
                        return i
            return None

        for i, (name, _) in enumerate(items):
            if raw in (str(i + 1), name.lower()):
                if i in unavailable:
                    msg = (
                        "required by other addons"
                        if context == "remove"
                        else "missing dependencies"
                    )
                    warn(f"'{name}' cannot be selected yet — {msg}.")
                    break
                return i

        warn(f"Please enter a number between 1 and {len(items)}, or a name.")
