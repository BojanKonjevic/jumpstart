"""Multi-selection TUI for addon selection during `zenit create`."""

from __future__ import annotations

import sys

from zenit.cli.ui import BOLD, CYAN, DIM, GREEN, RESET, YELLOW, warn
from zenit.schema.models import AddonConfig

from ._keys import tty_available
from ._render import (
    _DONE,
    _FOOTER_MULTI,
    _FOOTER_MULTI_SEARCH,
    ARROW,
    CHECK,
    DESC_INDENT,
    EMPTY,
    LABEL_WIDTH,
    LOCKED,
    TEMPLATE_REQUIRES,
    clear_lines,
    filter_indices,
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
    filtered_indices: list[int] | None = None,
    search_query: str = "",
    unavailable: set[int] | None = None,
    full_items: list[tuple[str, str, list[str]]] | None = None,
    context: str = "add",
) -> int:
    """Render the multi-selection TUI."""
    locked = locked or set()
    default_selected = default_selected or set()
    incompatible = incompatible or set()
    unavailable = unavailable or set()
    filtered = (
        filtered_indices if filtered_indices is not None else list(range(len(items)))
    )
    lines = 0

    for idx, orig_i in enumerate(filtered):
        name, desc = items[orig_i]
        is_cursor = idx == cursor
        is_unavailable = orig_i in unavailable
        is_incompatible = orig_i in incompatible

        prefix = f"  {ARROW} " if is_cursor else "     "

        if is_incompatible or is_unavailable:
            tick = "\033[2m—\033[0m  "
        elif orig_i in locked:
            tick = f"{LOCKED}  "
        elif orig_i in selected:
            tick = f"{CHECK}  "
        else:
            tick = f"{EMPTY}  "

        padded_name = f"{name:<{LABEL_WIDTH}}"
        if is_incompatible or is_unavailable:
            padded_label = f"{DIM}{padded_name}{RESET}"
        elif is_cursor:
            padded_label = f"{CYAN}{BOLD}{padded_name}{RESET}"
        elif orig_i in selected and orig_i not in locked:
            padded_label = f"{GREEN}{padded_name}{RESET}"
        else:
            padded_label = padded_name

        desc_text = f"{DIM}{desc}{RESET}"

        reqs = requires_map.get(name, [])
        req_hint = ""
        if reqs and orig_i not in locked and not is_incompatible and not is_unavailable:
            req_hint = f"  {DIM}(needs {', '.join(reqs)}){RESET}"

        extra = ""
        if is_incompatible:
            extra = f"  {DIM}(fastapi only){RESET}"
        elif is_unavailable and full_items and orig_i < len(full_items):
            reasons = full_items[orig_i][2]
            if reasons:
                parts = []
                template_blocks = [r for r in reasons if r.startswith("__template__")]
                addon_deps = [r for r in reasons if not r.startswith("__template__")]
                if addon_deps:
                    label = "required by" if context == "remove" else "needs"
                    parts.append(f"{label} {', '.join(addon_deps)}")
                if template_blocks:
                    tmpl = template_blocks[0].replace("__template__", "")
                    parts.append(f"required by {tmpl} template")
                if parts:
                    extra = f"  {DIM}({', '.join(parts)}){RESET}"
        elif orig_i in default_selected and orig_i not in locked and not is_cursor:
            extra = f"  {DIM}(default){RESET}"

        sys.stdout.write(
            f"{prefix}{tick}{padded_label}{DESC_INDENT}{desc_text}{req_hint}{extra}\n"
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
        sys.stdout.write(f"  {_FOOTER_MULTI_SEARCH}\n")
        lines += 3
    else:
        sys.stdout.write(f"\n  {_FOOTER_MULTI}\n")
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
    unavailable: set[int] | None = None,
    full_items: list[tuple[str, str, list[str]]] | None = None,
    context: str = "add",
) -> list[str]:
    incompatible = incompatible or set()
    unavailable = unavailable or set()
    print(f"\n  {BOLD}{prompt}{RESET}\n")
    n_items = len(items)
    reserve_lines(n_items + 2)
    clear_lines(n_items + 2)

    cursor = 0
    search_query = ""
    filtered_indices_list = filter_indices(items, search_query)
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
            filtered_indices=filtered_indices_list,
            search_query=search_query,
            unavailable=unavailable,
            full_items=full_items,
            context=context,
        )

    def on_key(key: str) -> object:
        nonlocal cursor, flash, locked, search_query, filtered_indices_list
        flash = ""

        if key == "\x1b[A":
            if filtered_indices_list:
                cursor = (cursor - 1) % len(filtered_indices_list)
        elif key == "\x1b[B":
            if filtered_indices_list:
                cursor = (cursor + 1) % len(filtered_indices_list)
        elif key == " ":
            if not filtered_indices_list:
                return None
            orig_idx = filtered_indices_list[cursor]
            item_name = items[orig_idx][0]
            if orig_idx in incompatible:
                flash = f"{item_name} is not available in this template"
            elif orig_idx in unavailable:
                reasons = full_items[orig_idx][2] if full_items else []
                template_blocks = [r for r in reasons if r.startswith("__template__")]
                addon_deps = [r for r in reasons if not r.startswith("__template__")]
                if addon_deps:
                    label = "required by" if context == "remove" else "needs"
                    flash = f"{item_name} {label}: {', '.join(addon_deps)}"
                elif template_blocks:
                    tmpl = template_blocks[0].replace("__template__", "")
                    flash = f"{item_name} is required by the {tmpl} template"
                else:
                    flash = f"{item_name} is not available"
            elif orig_idx in locked:
                if orig_idx in always_locked:
                    flash = f"{item_name} is required by the template"
                else:
                    dependents = [
                        items[i][0]
                        for i in selected
                        if item_name in requires_map.get(items[i][0], [])
                    ]
                    flash = f"{item_name} is required by {', '.join(dependents)}"
            elif orig_idx in selected:
                selected.discard(orig_idx)
                for i, (name, _) in enumerate(items):
                    if (
                        item_name in requires_map.get(name, [])
                        and i not in always_locked
                    ):
                        selected.discard(i)
            else:
                selected.add(orig_idx)
                for req in requires_map.get(item_name, []):
                    if req in name_to_idx:
                        selected.add(name_to_idx[req])
        elif key in ("\r", "\n"):
            return _DONE
        elif key == "\x1b":
            search_query = ""
            filtered_indices_list = filter_indices(items, search_query)
            cursor = 0
        elif key in ("\x7f", "\b"):
            search_query = search_query[:-1]
            filtered_indices_list = filter_indices(items, search_query)
            cursor = 0
        elif key == "\x03":
            show_cursor()
            print()
            sys.exit(0)
        elif len(key) == 1 and key.isprintable():
            search_query += key
            filtered_indices_list = filter_indices(items, search_query)
            cursor = 0
        locked = _compute_locked()
        return None

    run_tui(render, on_key)

    # Strip incompatible / unavailable addons from the final selection (shouldn't
    # be there, but guard anyway).
    chosen = [
        items[i][0]
        for i in sorted(selected)
        if i not in incompatible and i not in unavailable
    ]
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


def prompt_multi_addon(
    items: list[tuple[str, str, list[str]]],
    unavailable_indices: set[int] | None = None,
    context: str = "add",
    prompt: str = "Select addons:",
) -> list[str]:
    """Multi-select TUI for add/remove context.

    Returns the list of selected addon IDs.  Unlike ``prompt_addons`` this
    has no template concept — it simply shows items and lets the user pick
    any number of available ones.
    """
    unavailable_indices = unavailable_indices or set()
    display_items = [(name, desc) for name, desc, _ in items]

    if not tty_available():
        return _fallback_multi_addon(items, unavailable_indices, context)

    return _tui_multi(
        prompt,
        display_items,
        requires_map={},
        always_locked=set(),
        unavailable=unavailable_indices,
        full_items=items,
        context=context,
    )


def _fallback_multi_addon(
    items: list[tuple[str, str, list[str]]],
    unavailable_indices: set[int],
    context: str = "add",
) -> list[str]:
    """Fallback numbered-list multi-picker for non-tty environments."""
    action = "remove" if context == "remove" else "add"

    print(f"\n  Select addon(s) to {action}:\n")
    for i, (addon_id, desc, reasons) in enumerate(items, 1):
        is_unavailable = (i - 1) in unavailable_indices
        markers = []
        if is_unavailable and reasons:
            template_blocks = [r for r in reasons if r.startswith("__template__")]
            addon_deps = [r for r in reasons if not r.startswith("__template__")]
            if addon_deps:
                label = "required by" if context == "remove" else "needs"
                markers.append(f"{label} {', '.join(addon_deps)}")
            if template_blocks:
                tmpl = template_blocks[0].replace("__template__", "")
                markers.append(f"required by {tmpl} template")
        suffix = f"  {DIM}({', '.join(markers)}){RESET}" if markers else ""
        print(f"    {CYAN}{i}){RESET} {addon_id:<18} {DIM}—{RESET} {desc}{suffix}")
    print()

    while True:
        try:
            raw = input(
                "  Addons [space-separated numbers or names, or enter to cancel]: "
            ).strip()
        except EOFError, KeyboardInterrupt:
            print()
            sys.exit(0)

        if not raw:
            return []

        selected: list[str] = []
        valid = True
        for token in raw.split():
            # Try by number first
            if token.isdigit():
                idx = int(token) - 1
                if idx < 0 or idx >= len(items):
                    warn(f"{token} is out of range — pick between 1 and {len(items)}.")
                    valid = False
                    break
                addon_id = items[idx][0]
                if idx in unavailable_indices:
                    warn(
                        f"'{addon_id}' cannot be selected — "
                        + (
                            "it is required by other addons"
                            if context == "remove"
                            else "dependencies not met"
                        )
                        + "."
                    )
                    valid = False
                    break
                if addon_id not in selected:
                    selected.append(addon_id)
            else:
                # Try by name
                name_lower = token.lower()
                matched = False
                for idx, (addon_id, _, _) in enumerate(items):
                    if addon_id.lower() == name_lower and addon_id not in selected:
                        if idx in unavailable_indices:
                            warn(
                                f"'{addon_id}' cannot be selected — "
                                + (
                                    "it is required by other addons"
                                    if context == "remove"
                                    else "dependencies not met"
                                )
                                + "."
                            )
                            valid = False
                            break
                        selected.append(addon_id)
                        matched = True
                        break
                if not matched:
                    warn(f"Unknown addon '{token}'.")
                    valid = False
                    break
        if valid:
            return selected
