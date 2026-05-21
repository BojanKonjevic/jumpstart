"""Single-selection TUI (template picker and `zenit add` picker)."""

from __future__ import annotations

import sys

from zenit.cli.ui import BOLD, DIM, GREEN, RESET

from ._keys import tty_available
from ._render import (
    _DONE,
    TEMPLATES,
    clear_lines,
    render_single,
    reserve_lines,
    run_fallback,
    run_tui,
)


def prompt_template(default: str | None = None) -> str:
    if not tty_available():
        return _fallback_template(default)

    cursor = 0
    if default is not None:
        for i, (name, _) in enumerate(TEMPLATES):
            if name == default:
                cursor = i
                break

    print(f"\n  {BOLD}Select a base template:{RESET}\n")
    reserve_lines(len(TEMPLATES) + 2)
    clear_lines(len(TEMPLATES) + 2)

    def render() -> int:
        return render_single(TEMPLATES, cursor, default_name=default)

    def on_key(key: str) -> object:
        nonlocal cursor
        if key in ("\x1b[A", "k"):
            cursor = (cursor - 1) % len(TEMPLATES)
        elif key in ("\x1b[B", "j"):
            cursor = (cursor + 1) % len(TEMPLATES)
        elif key in ("\r", "\n", " "):
            return _DONE
        elif key == "\x03":
            print()
            sys.exit(0)
        return None

    run_tui(render, on_key)

    name, desc = TEMPLATES[cursor]
    clear_lines(render_single(TEMPLATES, cursor, default_name=default))
    print(f"  {GREEN}✓{RESET}  {BOLD}{name}{RESET}  {DIM}{desc}{RESET}\n")
    return name


def prompt_single_addon(
    items: list[tuple[str, str, list[str]]],
    unavailable_indices: set[int] | None = None,
) -> str | None:
    if not tty_available():
        return _fallback_single_add(items, unavailable_indices or set())

    unavailable_indices = unavailable_indices or set()
    display_items = [(name, desc) for name, desc, _ in items]

    print(f"\n  {BOLD}Select an addon to add:{RESET}\n")
    reserve_lines(len(display_items) + 2)
    clear_lines(len(display_items) + 2)

    cursor = 0
    flash = ""

    def render() -> int:
        return render_single(
            display_items,
            cursor,
            unavailable=unavailable_indices,
            full_items=items,
            flash=flash,
        )

    def on_key(key: str) -> object:
        nonlocal cursor, flash
        flash = ""
        if key in ("\x1b[A", "k"):
            cursor = (cursor - 1) % len(display_items)
        elif key in ("\x1b[B", "j"):
            cursor = (cursor + 1) % len(display_items)
        elif key in ("\r", "\n", " "):
            if cursor in unavailable_indices:
                addon_id, _, reqs = items[cursor]
                template_blocks = [r for r in reqs if r.startswith("__template__")]
                addon_deps = [r for r in reqs if not r.startswith("__template__")]
                if template_blocks:
                    tmpl = template_blocks[0].replace("__template__", "")
                    flash = f"{addon_id} is required by the {tmpl} template and cannot be removed"
                elif addon_deps:
                    flash = f"{addon_id} requires: {', '.join(addon_deps)} — remove those first"
                return None
            return _DONE
        elif key == "\x03":
            print()
            sys.exit(0)
        return None

    run_tui(render, on_key)

    if cursor in unavailable_indices:
        clear_lines(render())
        print(f"  {DIM}No addon selected.{RESET}\n")
        return None

    name, desc = display_items[cursor]
    clear_lines(render())
    print(f"  {GREEN}✓{RESET}  {BOLD}{name}{RESET}  {DIM}{desc}{RESET}\n")
    return name


# ── Fallbacks (non-tty) ───────────────────────────────────────────────────────


def _fallback_template(default: str | None = None) -> str:
    print("\n  Select a base template:\n")
    idx = run_fallback(TEMPLATES, default_name=default, prompt_text="Template")
    if idx is None:
        return TEMPLATES[0][0]
    return TEMPLATES[idx][0]


def _fallback_single_add(
    items: list[tuple[str, str, list[str]]],
    unavailable_indices: set[int],
) -> str | None:
    display_items = [(name, desc) for name, desc, _ in items]
    print("\n  Select an addon to add:\n")
    idx = run_fallback(
        display_items,
        unavailable=unavailable_indices,
        full_items=items,
        prompt_text="Addon",
    )
    if idx is None:
        return None
    return items[idx][0]
