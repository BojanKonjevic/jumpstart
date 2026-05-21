"""Multi-selection TUI for addon selection during `zenit create`."""

from __future__ import annotations

import sys

from zenit.cli.ui import BOLD, CYAN, DIM, GREEN, RESET, YELLOW, warn
from zenit.schema.models import AddonConfig

from ._keys import tty_available
from ._render import (
    _DONE,
    ARROW,
    CHECK,
    DESC_INDENT,
    EMPTY,
    LABEL_WIDTH,
    LOCKED,
    TEMPLATE_REQUIRES,
    clear_lines,
    reserve_lines,
    run_tui,
    show_cursor,
)


def _render_multi(
    items: list[tuple[str, str]],
    cursor: int,
    selected: set[int],
    requires_map: dict[str, list[str]],
    locked: set[int] | None = None,
    flash: str = "",
    default_selected: set[int] | None = None,
    incompatible: set[int] | None = None,
) -> int:
    """Render the multi-selection TUI."""
    locked = locked or set()
    default_selected = default_selected or set()
    incompatible = incompatible or set()
    lines = 0

    for i, (name, desc) in enumerate(items):
        prefix = f"  {ARROW} " if i == cursor else "     "

        if i in incompatible:
            tick = "\033[2m—\033[0m  "
        elif i in locked:
            tick = f"{LOCKED}  "
        elif i in selected:
            tick = f"{CHECK}  "
        else:
            tick = f"{EMPTY}  "

        padded_name = f"{name:<{LABEL_WIDTH}}"
        if i in incompatible:
            padded_label = f"{DIM}{padded_name}{RESET}"
        elif i == cursor:
            padded_label = f"{CYAN}{BOLD}{padded_name}{RESET}"
        elif i in selected and i not in locked:
            padded_label = f"{GREEN}{padded_name}{RESET}"
        else:
            padded_label = padded_name

        desc_text = f"{DIM}{desc}{RESET}"

        reqs = requires_map.get(name, [])
        req_hint = ""
        if reqs and i not in locked and i not in incompatible:
            req_hint = f"  {DIM}(needs {', '.join(reqs)}){RESET}"

        extra = ""
        if i in incompatible:
            extra = f"  {DIM}(fastapi only){RESET}"
        elif i in default_selected and i not in locked and i != cursor:
            extra = f"  {DIM}(default){RESET}"

        sys.stdout.write(
            f"{prefix}{tick}{padded_label}{DESC_INDENT}{desc_text}{req_hint}{extra}\n"
        )
        lines += 1

    if flash:
        sys.stdout.write(f"\n  {YELLOW}⚠  {flash}{RESET}\n")
    else:
        sys.stdout.write(
            f"\n  {DIM}↑↓ navigate · space toggle · enter confirm{RESET}\n"
        )
    lines += 2
    sys.stdout.flush()
    return lines


def prompt_addons(
    available: list[AddonConfig],
    template: str = "",
    default_addons: list[str] | None = None,
) -> list[str]:
    """Interactive multi-select for addons during project creation."""
    if not available:
        return []

    items = [(cfg.id, cfg.description) for cfg in available]
    requires_map = {cfg.id: cfg.requires for cfg in available}

    if not tty_available():
        return _fallback_multi(
            items,
            requires_map,
            template,
            default_addons or [],
            available=available,
        )

    name_to_idx = {cfg.id: i for i, cfg in enumerate(available)}

    # Addons that the selected template auto-selects and locks.
    always_locked: set[int] = set()
    for req in TEMPLATE_REQUIRES.get(template, []):
        if req in name_to_idx:
            always_locked.add(name_to_idx[req])

    # Addons that declare a templates allowlist which doesn't include the
    # currently selected template — they cannot be used at all this run.
    incompatible: set[int] = set()
    for i, cfg in enumerate(available):
        if cfg.templates and template not in cfg.templates:
            incompatible.add(i)

    default_selected: set[int] = set()
    if default_addons:
        for addon_id in default_addons:
            if addon_id in name_to_idx and name_to_idx[addon_id] not in incompatible:
                default_selected.add(name_to_idx[addon_id])
        for idx in list(default_selected):
            for req in requires_map.get(items[idx][0], []):
                if req in name_to_idx:
                    default_selected.add(name_to_idx[req])

    return _tui_multi(
        "Select addons:",
        items,
        requires_map,
        always_locked,
        default_selected=default_selected,
        incompatible=incompatible,
    )


def _tui_multi(
    prompt: str,
    items: list[tuple[str, str]],
    requires_map: dict[str, list[str]],
    always_locked: set[int],
    default_selected: set[int] | None = None,
    incompatible: set[int] | None = None,
) -> list[str]:
    incompatible = incompatible or set()
    print(f"\n  {BOLD}{prompt}{RESET}\n")
    n_items = len(items)
    reserve_lines(n_items + 2)
    clear_lines(n_items + 2)

    cursor = 0
    selected: set[int] = set(always_locked)
    if default_selected:
        selected |= default_selected
    name_to_idx = {name: i for i, (name, _) in enumerate(items)}
    flash = ""

    def _compute_locked() -> set[int]:
        locked = set(always_locked)
        for sel_idx in selected:
            sel_name = items[sel_idx][0]
            for req in requires_map.get(sel_name, []):
                if req in name_to_idx:
                    locked.add(name_to_idx[req])
        return locked

    locked = _compute_locked()

    def render() -> int:
        return _render_multi(
            items,
            cursor,
            selected,
            requires_map,
            locked,
            flash,
            default_selected=default_selected,
            incompatible=incompatible,
        )

    def on_key(key: str) -> object:
        nonlocal cursor, flash, locked
        flash = ""
        if key in ("\x1b[A", "k"):
            cursor = (cursor - 1) % n_items
        elif key in ("\x1b[B", "j"):
            cursor = (cursor + 1) % n_items
        elif key == " ":
            item_name = items[cursor][0]
            if cursor in incompatible:
                flash = f"{item_name} is not available in this template"
            elif cursor in locked:
                if cursor in always_locked:
                    flash = f"{item_name} is required by the template"
                else:
                    dependents = [
                        items[i][0]
                        for i in selected
                        if item_name in requires_map.get(items[i][0], [])
                    ]
                    flash = f"{item_name} is required by {', '.join(dependents)}"
            elif cursor in selected:
                selected.discard(cursor)
                for i, (name, _) in enumerate(items):
                    if (
                        item_name in requires_map.get(name, [])
                        and i not in always_locked
                    ):
                        selected.discard(i)
            else:
                selected.add(cursor)
                for req in requires_map.get(item_name, []):
                    if req in name_to_idx:
                        selected.add(name_to_idx[req])
        elif key in ("\r", "\n"):
            return _DONE
        elif key == "\x03":
            show_cursor()
            print()
            sys.exit(0)
        locked = _compute_locked()
        return None

    run_tui(render, on_key)

    # Strip incompatible addons from the final selection (shouldn't be there,
    # but guard anyway).
    chosen = [items[i][0] for i in sorted(selected) if i not in incompatible]
    clear_lines(render())

    if chosen:
        names = ", ".join(f"{GREEN}{n}{RESET}" for n in chosen)
        print(f"  {GREEN}✓{RESET}  {names}\n")
    else:
        print(f"  {DIM}No addons selected.{RESET}\n")
    return chosen


def _fallback_multi(
    items: list[tuple[str, str]],
    requires_map: dict[str, list[str]],
    template: str,
    default_addon_names: list[str],
    available: list[AddonConfig] | None = None,
) -> list[str]:
    always_locked_names = set(TEMPLATE_REQUIRES.get(template, []))

    # Build incompatible set by addon id for the fallback path.
    incompatible_names: set[str] = set()
    if available:
        for cfg in available:
            if cfg.templates and template not in cfg.templates:
                incompatible_names.add(cfg.id)

    if not items:
        return list(always_locked_names)

    default_set = set(default_addon_names) - incompatible_names
    has_defaults = bool(default_set - always_locked_names)

    print(
        f"\n  Select addons: {DIM}("
        + (
            "enter for defaults"
            if has_defaults
            else "space-separated numbers, or enter to skip"
        )
        + f"){RESET}\n"
    )
    for i, (addon_id, desc) in enumerate(items, 1):
        is_incompatible = addon_id in incompatible_names
        locked_mark = (
            f" {DIM}(required){RESET}" if addon_id in always_locked_names else ""
        )
        incompat_mark = (
            f" {DIM}(fastapi only — not available){RESET}" if is_incompatible else ""
        )
        default_mark = (
            f" {DIM}(default){RESET}"
            if addon_id in default_set and addon_id not in always_locked_names
            else ""
        )
        print(
            f"    {CYAN}{i}){RESET} {addon_id:<18} {DIM}—{RESET} {desc}"
            f"{locked_mark}{incompat_mark}{default_mark}"
        )
    print()

    def _build_defaults() -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for name in list(always_locked_names) + list(default_set):
            if name not in seen and name not in incompatible_names:
                seen.add(name)
                result.append(name)
        return result

    while True:
        try:
            raw = input(
                "  Addons [e.g. 1 3"
                + (", or enter for defaults" if has_defaults else ", or leave blank")
                + "]: "
            ).strip()
        except EOFError, KeyboardInterrupt:
            print()
            sys.exit(0)

        if not raw:
            return _build_defaults()

        selected: list[str] = list(always_locked_names)
        valid = True
        for token in raw.split():
            if not token.isdigit():
                warn(f"'{token}' is not a number.")
                valid = False
                break
            idx = int(token) - 1
            if idx < 0 or idx >= len(items):
                warn(f"{token} is out of range — pick between 1 and {len(items)}.")
                valid = False
                break
            addon_id = items[idx][0]
            if addon_id in incompatible_names:
                warn(f"'{addon_id}' is not available for the '{template}' template.")
                valid = False
                break
            if addon_id not in selected:
                selected.append(addon_id)
                for req in requires_map.get(addon_id, []):
                    if req not in selected:
                        selected.append(req)
                        warn(f"Auto-selected '{req}' (required by '{addon_id}').")
        if valid:
            return selected
