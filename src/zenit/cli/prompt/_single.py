"""Single-selection TUI (template picker and `zenit add` picker)."""

from __future__ import annotations

import sys

from zenit.cli.ui import BOLD, DIM, GREEN, RESET

from ._keys import tty_available
from ._render import (
    _DONE,
    TEMPLATES,
    clear_lines,
    filter_indices,
    render_single,
    reserve_lines,
    run_fallback,
    run_tui,
)


def prompt_template(default: str | None = None) -> str:
    if not tty_available():
        return _fallback_template(default)

    cursor = 0
    search_query = ""
    filtered = list(range(len(TEMPLATES)))
    if default is not None:
        for i, (name, _) in enumerate(TEMPLATES):
            if name == default:
                cursor = i
                break

    print(f"\n  {BOLD}Select a base template:{RESET}\n")
    reserve_lines(len(TEMPLATES) + 2)
    clear_lines(len(TEMPLATES) + 2)

    def render() -> int:
        return render_single(
            TEMPLATES,
            cursor,
            default_name=default,
            filtered_indices=filtered,
            search_query=search_query,
        )

    def on_key(key: str) -> object:
        nonlocal cursor, search_query, filtered
        if key == "\x1b[A":
            if filtered:
                cursor = (cursor - 1) % len(filtered)
        elif key == "\x1b[B":
            if filtered:
                cursor = (cursor + 1) % len(filtered)
        elif key in ("\r", "\n", " "):
            return _DONE
        elif key == "\x1b":
            search_query = ""
            filtered = list(range(len(TEMPLATES)))
            cursor = 0
        elif key in ("\x7f", "\b"):
            search_query = search_query[:-1]
            filtered = filter_indices(TEMPLATES, search_query)
            cursor = 0
        elif key == "\x03":
            print()
            sys.exit(0)
        elif len(key) == 1 and key.isprintable():
            search_query += key
            filtered = filter_indices(TEMPLATES, search_query)
            cursor = 0
        return None

    run_tui(render, on_key)

    if filtered:
        orig_i = filtered[cursor]
        name, desc = TEMPLATES[orig_i]
        clear_lines(
            render_single(
                TEMPLATES,
                cursor,
                default_name=default,
                filtered_indices=filtered,
                search_query=search_query,
            )
        )
    else:
        name, desc = TEMPLATES[0]
        clear_lines(1)
    print(f"  {GREEN}✓{RESET}  {BOLD}{name}{RESET}  {DIM}{desc}{RESET}\n")
    return name


def prompt_single_addon(
    items: list[tuple[str, str, list[str]]],
    unavailable_indices: set[int] | None = None,
    context: str = "add",
) -> str | None:
    if not tty_available():
        return _fallback_single_add(
            items, unavailable_indices or set(), context=context
        )

    unavailable_indices = unavailable_indices or set()
    display_items = [(name, desc) for name, desc, _ in items]

    action = "remove" if context == "remove" else "add"
    print(f"\n  {BOLD}Select an addon to {action}:{RESET}\n")
    reserve_lines(len(display_items) + 2)
    clear_lines(len(display_items) + 2)

    cursor = 0
    flash = ""
    search_query = ""
    filtered = list(range(len(display_items)))

    def render() -> int:
        return render_single(
            display_items,
            cursor,
            unavailable=unavailable_indices,
            full_items=items,
            flash=flash,
            context=context,
            filtered_indices=filtered,
            search_query=search_query,
        )

    def on_key(key: str) -> object:
        nonlocal cursor, flash, search_query, filtered
        flash = ""
        if key == "\x1b[A":
            if filtered:
                cursor = (cursor - 1) % len(filtered)
        elif key == "\x1b[B":
            if filtered:
                cursor = (cursor + 1) % len(filtered)
        elif key in ("\r", "\n", " "):
            if not filtered:
                return None
            orig_i = filtered[cursor]
            if orig_i in unavailable_indices:
                addon_id, _, reqs = items[orig_i]
                template_blocks = [r for r in reqs if r.startswith("__template__")]
                addon_deps = [r for r in reqs if not r.startswith("__template__")]
                if template_blocks:
                    tmpl = template_blocks[0].replace("__template__", "")
                    flash = f"{addon_id} is required by the {tmpl} template and cannot be removed"
                elif addon_deps:
                    label = "required by" if context == "remove" else "needs"
                    flash = f"{addon_id} {label}: {', '.join(addon_deps)}"
                return None
            return _DONE
        elif key == "\x1b":
            search_query = ""
            filtered = list(range(len(display_items)))
            cursor = 0
        elif key in ("\x7f", "\b"):
            search_query = search_query[:-1]
            filtered = filter_indices(display_items, search_query)
            cursor = 0
        elif key == "\x03":
            print()
            sys.exit(0)
        elif len(key) == 1 and key.isprintable():
            search_query += key
            filtered = filter_indices(display_items, search_query)
            cursor = 0
        return None

    run_tui(render, on_key)

    if not filtered:
        clear_lines(render())
        print(f"  {DIM}No addon selected.{RESET}\n")
        return None

    orig_i = filtered[cursor]
    if orig_i in unavailable_indices:
        clear_lines(render())
        print(f"  {DIM}No addon selected.{RESET}\n")
        return None

    name, desc = display_items[orig_i]
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
    context: str = "add",
) -> str | None:
    display_items = [(name, desc) for name, desc, _ in items]
    action = "remove" if context == "remove" else "add"
    print(f"\n  Select an addon to {action}:\n")
    idx = run_fallback(
        display_items,
        unavailable=unavailable_indices,
        full_items=items,
        prompt_text="Addon",
        context=context,
    )
    if idx is None:
        return None
    return items[idx][0]
