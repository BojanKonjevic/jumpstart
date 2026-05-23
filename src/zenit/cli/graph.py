from __future__ import annotations

import json
import re
from collections.abc import Generator, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from zenit.schema.models import AddonConfig

from zenit.cli.ui import BOLD, CYAN, DIM, GREEN, RESET


@dataclass
class TreeNode:
    addon: AddonConfig
    depth: int
    is_installed: bool
    children: list[TreeNode] = field(default_factory=list)


def build_tree(
    addons: Sequence[AddonConfig],
    installed_ids: set[str],
    reverse: bool = False,
    depth_limit: int = 20,
) -> list[TreeNode]:
    addon_map = {a.id: a for a in addons}
    required_by: dict[str, list[str]] = {}
    for addon in addons:
        for req in addon.requires:
            required_by.setdefault(req, []).append(addon.id)

    if reverse:
        roots = [a for a in addons if a.requires]
        roots.sort(key=lambda a: a.id)
        forest = []
        for root in roots:
            child_nodes = [
                TreeNode(
                    addon=addon_map[req],
                    depth=1,
                    is_installed=req in installed_ids,
                )
                for req in sorted(root.requires)
                if req in addon_map
            ]
            forest.append(
                TreeNode(
                    addon=root,
                    depth=0,
                    is_installed=root.id in installed_ids,
                    children=child_nodes,
                )
            )
        return forest

    roots = [a for a in addons if not a.requires]
    roots.sort(key=lambda a: a.id)
    forest = []
    for root in roots:
        node = _build_node(
            root, 0, installed_ids, required_by, addon_map, set(), depth_limit
        )
        forest.append(node)
    return forest


def _build_node(
    addon: AddonConfig,
    depth: int,
    installed_ids: set[str],
    required_by: dict[str, list[str]],
    addon_map: dict[str, AddonConfig],
    visited: set[str],
    depth_limit: int,
) -> TreeNode:
    node = TreeNode(
        addon=addon,
        depth=depth,
        is_installed=addon.id in installed_ids,
    )
    if depth >= depth_limit or addon.id in visited:
        return node

    visited = visited | {addon.id}
    dependents = sorted(required_by.get(addon.id, []))
    for dep_id in dependents:
        if dep_id in addon_map:
            child = _build_node(
                addon_map[dep_id],
                depth + 1,
                installed_ids,
                required_by,
                addon_map,
                visited,
                depth_limit,
            )
            node.children.append(child)
    return node


_ANSI_RE = re.compile(r"\033\[[0-9;]*m")


def _visible_width(text: str) -> int:
    return len(_ANSI_RE.sub("", text))


def _iter_nodes(node: TreeNode) -> Generator[TreeNode, None, None]:
    yield node
    for child in node.children:
        yield from _iter_nodes(child)


def _collect_ids(forest: list[TreeNode]) -> set[str]:
    ids: set[str] = set()
    for tree in forest:
        for node in _iter_nodes(tree):
            ids.add(node.addon.id)
    return ids


def _render_children(
    children: list[TreeNode],
    prefix: str,
    lines: list[str],
    reverse: bool,
) -> None:
    for i, child in enumerate(children):
        is_last = i == len(children) - 1
        connector = "└── " if is_last else "├── "
        bullet = "●" if child.is_installed else "○"
        styled_bullet = (
            f"{GREEN}{bullet}{RESET}" if child.is_installed else f"{DIM}{bullet}{RESET}"
        )
        if child.is_installed:
            styled_name = f"{BOLD}{CYAN}{child.addon.id}{RESET}"
        else:
            styled_name = f"{DIM}{child.addon.id}{RESET}"
        if reverse:
            name_display = f"{DIM}depends on:{RESET} {styled_name}"
        else:
            name_display = styled_name
        styled_connector = f"{DIM}{connector}{RESET}"
        line = f"{prefix}{styled_connector}{styled_bullet} {name_display}"
        lines.append(line)
        extension = "    " if is_last else "│   "
        _render_children(child.children, prefix + extension, lines, reverse)


def render_terminal(
    forest: list[TreeNode],
    installed_ids: set[str],
    project_name: str | None = None,
    project_dir: str | None = None,
    reverse: bool = False,
) -> str:
    content_lines: list[str] = []

    content_lines.append("")

    for node in forest:
        bullet = "●" if node.is_installed else "○"
        styled_bullet = (
            f"{GREEN}{bullet}{RESET}" if node.is_installed else f"{DIM}{bullet}{RESET}"
        )
        styled_name = (
            f"{BOLD}{CYAN}{node.addon.id}{RESET}"
            if node.is_installed
            else f"{DIM}{node.addon.id}{RESET}"
        )
        content_lines.append(f"  {styled_bullet} {styled_name}")
        _render_children(node.children, "    ", content_lines, reverse)

    content_lines.append("")

    all_ids = _collect_ids(forest)
    installed_count = sum(1 for aid in all_ids if aid in installed_ids)
    available_count = len(all_ids) - installed_count
    summary = (
        f"  {GREEN}◉{RESET} installed {installed_count}"
        f"   {DIM}○{RESET} available {available_count}"
    )
    content_lines.append(summary)

    if project_name and project_dir:
        content_lines.append(f"  {project_name}  │  {project_dir}")

    visible_widths = [_visible_width(line) for line in content_lines]
    max_visible = max(visible_widths) if visible_widths else 0
    title = "Zenit Dependencies" if reverse else "Zenit Graph"
    frame_width = max(max_visible + 6, len(title) + 10)
    fill = frame_width - len(title) - 9
    top = f"╭─ {title} ──{'─' * fill}──╮"
    bottom = f"╰{'─' * (frame_width - 2)}╯"

    result_lines: list[str] = [top]
    for line in content_lines:
        visible = _visible_width(line)
        padding = frame_width - 6 - visible
        result_lines.append(f"│  {line}{' ' * padding}  │")
    result_lines.append(bottom)
    result_lines.append("")

    return "\n".join(result_lines)


def render_dot(forest: list[TreeNode]) -> str:
    lines: list[str] = ["digraph zenit {", "  rankdir=LR;"]
    for node in forest:
        _collect_dot_edges(node, lines)
    lines.append("}")
    return "\n".join(lines) + "\n"


def _collect_dot_edges(node: TreeNode, lines: list[str]) -> None:
    for child in node.children:
        lines.append(f'  "{node.addon.id}" -> "{child.addon.id}";')
        _collect_dot_edges(child, lines)


def render_json(
    forest: list[TreeNode],
    installed_ids: set[str],
    all_addons: Sequence[AddonConfig],
    project_name: str | None = None,
    project_dir: str | None = None,
    template: str | None = None,
) -> str:
    required_by: dict[str, list[str]] = {}
    for addon in all_addons:
        for req in addon.requires:
            required_by.setdefault(req, []).append(addon.id)

    addons_list: list[dict[str, object]] = []
    for addon in all_addons:
        addons_list.append(
            {
                "id": addon.id,
                "installed": addon.id in installed_ids,
                "requires": list(addon.requires),
                "required_by": sorted(required_by.get(addon.id, [])),
            }
        )

    return (
        json.dumps(
            {
                "project": {
                    "name": project_name,
                    "template": template,
                    "dir": project_dir,
                },
                "addons": addons_list,
            },
            indent=2,
        )
        + "\n"
    )
