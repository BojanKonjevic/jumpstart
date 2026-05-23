from __future__ import annotations

import json
import re
from unittest.mock import patch

from typer.testing import CliRunner

from zenit.cli.graph import (
    build_tree,
    render_dot,
    render_json,
    render_terminal,
)
from zenit.cli.main import app
from zenit.core.lockfile import ZenitLockfile
from zenit.schema.models import AddonConfig

runner = CliRunner()

_PATCH_LOCKFILE = "zenit.core.lockfile.read_lockfile"
_PATCH_ADDONS = "zenit.addons._registry.get_available_addons"


def _lf(template: str = "fastapi", addons: list[str] | None = None) -> ZenitLockfile:
    return ZenitLockfile(
        template=template,
        addons=addons or [],
        zenit_version="1.0.0",
        schema_version=2,
    )


def _addon(id: str, requires: list[str] | None = None) -> AddonConfig:
    return AddonConfig(id=id, description="", requires=requires or [])


# ── build_tree ─────────────────────────────────────────────────────────────────


class TestBuildTree:
    def test_build_tree_flat(self) -> None:
        addons = [_addon("docker"), _addon("postgres"), _addon("redis")]
        forest = build_tree(addons, installed_ids=set())
        assert len(forest) == 3
        for tree in forest:
            assert tree.children == []

    def test_build_tree_chain(self) -> None:
        a = _addon("a")
        b = _addon("b", requires=["a"])
        c = _addon("c", requires=["b"])
        forest = build_tree([a, b, c], installed_ids=set())
        assert len(forest) == 1
        assert forest[0].addon.id == "a"
        assert len(forest[0].children) == 1
        assert forest[0].children[0].addon.id == "b"
        assert len(forest[0].children[0].children) == 1
        assert forest[0].children[0].children[0].addon.id == "c"

    def test_build_tree_fork(self) -> None:
        a = _addon("a")
        b = _addon("b", requires=["a"])
        c = _addon("c", requires=["a"])
        forest = build_tree([a, b, c], installed_ids=set())
        assert len(forest) == 1
        assert forest[0].addon.id == "a"
        assert len(forest[0].children) == 2
        assert forest[0].children[0].addon.id == "b"
        assert forest[0].children[1].addon.id == "c"

    def test_build_tree_merge(self) -> None:
        a = _addon("a")
        b = _addon("b")
        c = _addon("c", requires=["a", "b"])
        forest = build_tree([a, b, c], installed_ids=set())
        assert len(forest) == 2
        ids = {t.addon.id for t in forest}
        assert ids == {"a", "b"}
        for tree in forest:
            assert tree.addon.id in ("a", "b")
            assert len(tree.children) == 1
            assert tree.children[0].addon.id == "c"

    def test_build_tree_installed_filter(self) -> None:
        a = _addon("a")
        b = _addon("b", requires=["a"])
        # Only a and b are installed
        installed = {"a", "b"}
        # Simulate filtering: only pass installed addons to build_tree
        forest = build_tree([a, b], installed_ids=installed)
        assert len(forest) == 1
        assert forest[0].addon.id == "a"
        assert forest[0].is_installed is True
        assert len(forest[0].children) == 1
        assert forest[0].children[0].addon.id == "b"
        assert forest[0].children[0].is_installed is True

    def test_build_tree_all_flag(self) -> None:
        a = _addon("a")
        b = _addon("b", requires=["a"])
        c = _addon("c")
        installed = {"a"}
        forest = build_tree([a, b, c], installed_ids=installed)
        assert len(forest) == 2
        for tree in forest:
            if tree.addon.id == "a":
                assert tree.is_installed is True
                assert len(tree.children) == 1
                assert tree.children[0].addon.id == "b"
                assert tree.children[0].is_installed is False
            elif tree.addon.id == "c":
                assert tree.is_installed is False

    def test_build_tree_reverse(self) -> None:
        a = _addon("a")
        b = _addon("b", requires=["a"])
        c = _addon("c", requires=["a"])
        d = _addon("d")
        forest = build_tree([a, b, c, d], installed_ids=set(), reverse=True)
        # Roots: addons with requirements = b and c
        assert len(forest) == 2
        assert forest[0].addon.id == "b"
        assert len(forest[0].children) == 1
        assert forest[0].children[0].addon.id == "a"
        assert forest[1].addon.id == "c"
        assert len(forest[1].children) == 1
        assert forest[1].children[0].addon.id == "a"

    def test_build_tree_reverse_no_children_beyond_direct(self) -> None:
        a = _addon("a")
        b = _addon("b", requires=["a"])
        c = _addon("c", requires=["b"])
        forest = build_tree([a, b, c], installed_ids=set(), reverse=True)
        # Roots: addons with requirements = b, c
        assert len(forest) == 2
        # b depends on a
        assert forest[0].addon.id == "b"
        assert len(forest[0].children) == 1
        assert forest[0].children[0].addon.id == "a"
        # c depends on b (direct only, 1 level)
        assert forest[1].addon.id == "c"
        assert len(forest[1].children) == 1
        assert forest[1].children[0].addon.id == "b"

    def test_build_tree_depth_limit(self) -> None:
        addons = []
        for i in range(6):
            reqs = [f"n{i - 1}"] if i > 0 else []
            addons.append(AddonConfig(id=f"n{i}", description="", requires=reqs))
        forest = build_tree(addons, installed_ids=set(), depth_limit=3)
        assert len(forest) == 1
        n0 = forest[0]
        assert n0.addon.id == "n0"
        assert len(n0.children) == 1
        assert n0.children[0].addon.id == "n1"
        assert len(n0.children[0].children) == 1
        assert n0.children[0].children[0].addon.id == "n2"
        assert len(n0.children[0].children[0].children) == 1
        assert n0.children[0].children[0].children[0].addon.id == "n3"
        assert len(n0.children[0].children[0].children[0].children) == 0

    def test_build_tree_cycle_safe(self) -> None:
        a = _addon("a", requires=["b"])
        b = _addon("b", requires=["a"])
        forest = build_tree([a, b], installed_ids=set())
        # Neither is a root (both have requires), so forest is empty
        assert len(forest) == 0

    def test_build_tree_cycle_in_chain(self) -> None:
        a = _addon("a")
        b = _addon("b", requires=["a"])
        c = _addon("c", requires=["b"])
        d = _addon("d", requires=["c"])
        # Create cycle: b also requires d
        b.requires = ["a", "d"]
        forest = build_tree([a, b, c, d], installed_ids=set(), depth_limit=10)
        assert len(forest) == 1
        assert forest[0].addon.id == "a"
        # b is a child of a
        assert len(forest[0].children) == 1
        assert forest[0].children[0].addon.id == "b"
        # c is a child of b
        assert len(forest[0].children[0].children) == 1
        assert forest[0].children[0].children[0].addon.id == "c"
        # d is a child of c
        assert len(forest[0].children[0].children[0].children) == 1
        assert forest[0].children[0].children[0].children[0].addon.id == "d"
        # d has b as child (cycle edge), but b at depth 4 has no children (cycle guard)
        assert len(forest[0].children[0].children[0].children[0].children) == 1
        assert (
            len(forest[0].children[0].children[0].children[0].children[0].children) == 0
        )


# ── render_terminal ────────────────────────────────────────────────────────────


class TestRenderTerminal:
    def test_render_connectors(self) -> None:
        a = _addon("a")
        b = _addon("b", requires=["a"])
        c = _addon("c", requires=["a"])
        d = _addon("d", requires=["b"])
        e = _addon("e", requires=["b"])
        forest = build_tree([a, b, c, d, e], installed_ids={"a", "b", "c", "d", "e"})
        output = render_terminal(forest, installed_ids={"a", "b", "c", "d", "e"})
        assert "├──" in output
        assert "└──" in output

    def test_render_connectors_deep(self) -> None:
        a = _addon("a")
        b = _addon("b", requires=["a"])
        c = _addon("c", requires=["a"])
        b2 = _addon("b2", requires=["b"])
        b3 = _addon("b3", requires=["b"])
        forest = build_tree(
            [a, b, c, b2, b3], installed_ids={"a", "b", "c", "b2", "b3"}
        )
        output = render_terminal(forest, installed_ids={"a", "b", "c", "b2", "b3"})
        # a → [b, c], b → [b2, b3]
        # Expect ├── before b (not last), └── before c (last)
        # Expect │   └── before b2 and b3 under b
        assert "├──" in output
        assert "└──" in output
        assert "│" in output

    def test_render_colors_installed(self) -> None:
        a = _addon("a")
        forest = build_tree([a], installed_ids={"a"})
        output = render_terminal(forest, installed_ids={"a"})
        # GREEN (0;32) for installed bullet
        assert "\033[0;32m" in output
        # BOLD (1) + CYAN (0;36) for installed name
        assert "\033[1m" in output
        assert "\033[0;36m" in output

    def test_render_colors_available(self) -> None:
        a = _addon("a")
        forest = build_tree([a], installed_ids=set())
        output = render_terminal(forest, installed_ids=set())
        # DIM (2) for available bullet and name
        assert "\033[2m" in output

    def test_render_frame(self) -> None:
        a = _addon("a")
        forest = build_tree([a], installed_ids={"a"})
        output = render_terminal(forest, installed_ids={"a"})
        lines = output.split("\n")
        assert lines[0].startswith("╭─")
        assert lines[0].endswith("╮")
        assert lines[-2].startswith("╰")  # -1 is empty string
        assert lines[-2].endswith("╯")
        for line in lines[1:-2]:
            assert line.startswith("│")
            assert line.endswith("│")

    def test_render_frame_width(self) -> None:
        a = _addon("a")
        b = _addon("longname", requires=["a"])
        forest = build_tree([a, b], installed_ids={"a", "b"})
        output = render_terminal(forest, installed_ids={"a", "b"})
        lines = output.split("\n")
        frame_width = len(lines[0])
        # Stripping ANSI codes since they inflate byte-length but occupy 0 visible width
        visible_lines = [re.sub(r"\x1b\[[0-9;]*m", "", line) for line in lines[1:-2]]
        for vline in visible_lines:
            assert len(vline) == frame_width

    def test_render_reverse(self) -> None:
        a = _addon("a")
        b = _addon("b", requires=["a"])
        forest = build_tree([a, b], installed_ids={"a", "b"}, reverse=True)
        output = render_terminal(forest, installed_ids={"a", "b"}, reverse=True)
        # Children show "depends on:" label
        assert "depends on:" in output
        # Title changes
        assert "Dependencies" in output

    def test_render_empty_forest(self) -> None:
        output = render_terminal([], installed_ids=set())
        assert "╭─" in output
        assert "installed 0" in output
        assert "available 0" in output


# ── render_dot ─────────────────────────────────────────────────────────────────


class TestRenderDot:
    def test_render_dot(self) -> None:
        a = _addon("a")
        b = _addon("b", requires=["a"])
        c = _addon("c", requires=["a"])
        forest = build_tree([a, b, c], installed_ids=set())
        output = render_dot(forest)
        assert output.startswith("digraph zenit {")
        assert output.endswith("}\n")
        assert '  "a" -> "b";' in output
        assert '  "a" -> "c";' in output
        assert "  rankdir=LR;" in output

    def test_render_dot_no_edges(self) -> None:
        a = _addon("a")
        b = _addon("b")
        forest = build_tree([a, b], installed_ids=set())
        output = render_dot(forest)
        assert '  "a"' not in output  # no edges means no node refs in output
        assert output.count("->") == 0

    def test_render_dot_chain(self) -> None:
        a = _addon("a")
        b = _addon("b", requires=["a"])
        c = _addon("c", requires=["b"])
        forest = build_tree([a, b, c], installed_ids=set())
        output = render_dot(forest)
        assert '  "a" -> "b";' in output
        assert '  "b" -> "c";' in output


# ── render_json ────────────────────────────────────────────────────────────────


class TestRenderJson:
    def test_render_json(self) -> None:
        a = _addon("a")
        b = _addon("b", requires=["a"])
        all_addons = [a, b]
        forest = build_tree(all_addons, installed_ids={"a", "b"})
        output = render_json(
            forest,
            installed_ids={"a", "b"},
            all_addons=all_addons,
            project_name="myapp",
            project_dir="/home/user/myapp",
            template="fastapi",
        )
        data = json.loads(output)
        assert data["project"]["name"] == "myapp"
        assert data["project"]["template"] == "fastapi"
        assert data["project"]["dir"] == "/home/user/myapp"
        assert len(data["addons"]) == 2
        addon_map = {a["id"]: a for a in data["addons"]}
        assert addon_map["a"]["installed"] is True
        assert addon_map["a"]["requires"] == []
        assert addon_map["a"]["required_by"] == ["b"]
        assert addon_map["b"]["installed"] is True
        assert addon_map["b"]["requires"] == ["a"]
        assert addon_map["b"]["required_by"] == []

    def test_render_json_no_project(self) -> None:
        a = _addon("a")
        forest = build_tree([a], installed_ids=set())
        output = render_json(
            forest,
            installed_ids=set(),
            all_addons=[a],
            project_name=None,
            project_dir=None,
            template=None,
        )
        data = json.loads(output)
        assert data["project"]["name"] is None
        assert data["project"]["template"] is None
        assert data["project"]["dir"] is None
        assert len(data["addons"]) == 1


# ── CLI integration tests ──────────────────────────────────────────────────────


class TestCliGraph:
    def test_cli_inside_project(self) -> None:
        addons = [_addon("docker"), _addon("postgres"), _addon("redis")]
        lf = _lf(template="fastapi", addons=["docker", "redis"])
        with (
            patch(_PATCH_LOCKFILE, return_value=lf),
            patch(_PATCH_ADDONS, return_value=addons),
        ):
            result = runner.invoke(app, ["graph"])
        assert result.exit_code == 0
        assert "docker" in result.output
        assert "redis" in result.output
        assert "postgres" not in result.output

    def test_cli_outside_project(self) -> None:
        addons = [_addon("docker"), _addon("postgres")]
        with (
            patch(_PATCH_LOCKFILE, return_value=None),
            patch(_PATCH_ADDONS, return_value=addons),
        ):
            result = runner.invoke(app, ["graph"])
        assert result.exit_code == 1
        assert "No .zenit.toml found" in result.output

    def test_cli_outside_project_all(self) -> None:
        addons = [_addon("docker"), _addon("postgres")]
        with (
            patch(_PATCH_LOCKFILE, return_value=None),
            patch(_PATCH_ADDONS, return_value=addons),
        ):
            result = runner.invoke(app, ["graph", "--all"])
        assert result.exit_code == 0
        assert "docker" in result.output
        assert "postgres" in result.output

    def test_cli_dot_flag(self) -> None:
        a = _addon("a")
        b = _addon("b", requires=["a"])
        lf = _lf(template="fastapi", addons=["a", "b"])
        with (
            patch(_PATCH_LOCKFILE, return_value=lf),
            patch(_PATCH_ADDONS, return_value=[a, b]),
        ):
            result = runner.invoke(app, ["graph", "--dot"])
        assert result.exit_code == 0
        assert result.output.startswith("digraph zenit {")
        assert '  "a" -> "b";' in result.output

    def test_cli_json_flag(self) -> None:
        a = _addon("a")
        b = _addon("b", requires=["a"])
        lf = _lf(template="fastapi", addons=["a", "b"])
        with (
            patch(_PATCH_LOCKFILE, return_value=lf),
            patch(_PATCH_ADDONS, return_value=[a, b]),
        ):
            result = runner.invoke(app, ["graph", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "project" in data
        assert "addons" in data

    def test_cli_reverse_flag(self) -> None:
        a = _addon("a")
        b = _addon("b", requires=["a"])
        lf = _lf(template="fastapi", addons=["a", "b"])
        with (
            patch(_PATCH_LOCKFILE, return_value=lf),
            patch(_PATCH_ADDONS, return_value=[a, b]),
        ):
            result = runner.invoke(app, ["graph", "--reverse"])
        assert result.exit_code == 0
        assert "depends on:" in result.output

    def test_cli_no_addons(self) -> None:
        lf = _lf(template="fastapi", addons=[])
        with (
            patch(_PATCH_LOCKFILE, return_value=lf),
            patch(_PATCH_ADDONS, return_value=[]),
        ):
            result = runner.invoke(app, ["graph"])
        assert result.exit_code == 0
        assert "No addons to show" in result.output

    def test_cli_no_addons_outside_with_all(self) -> None:
        with (
            patch(_PATCH_LOCKFILE, return_value=None),
            patch(_PATCH_ADDONS, return_value=[]),
        ):
            result = runner.invoke(app, ["graph", "--all"])
        assert result.exit_code == 0
        assert "No addons to show" in result.output

    def test_cli_all_flag_shows_all(self) -> None:
        a = _addon("a")
        b = _addon("b")
        c = _addon("c", requires=["a"])
        lf = _lf(template="fastapi", addons=["a"])
        with (
            patch(_PATCH_LOCKFILE, return_value=lf),
            patch(_PATCH_ADDONS, return_value=[a, b, c]),
        ):
            result = runner.invoke(app, ["graph", "--all"])
        assert result.exit_code == 0
        assert "a" in result.output
        assert "b" in result.output
        assert "c" in result.output
