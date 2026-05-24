"""Unit tests for justfile recipe removal — block parser + end-to-end removal.

Covers the two-pass block parser (``_parse_justfile_blocks``) and the
``_remove_just_recipes`` helper that replaces the old whitespace heuristic.

Test matrix
-----------
- Simple recipe with no attributes — baseline
- Recipe with a ``[private]`` attribute — attribute removed with recipe
- Recipe with multiple attributes — all removed together
- Alias to a removed recipe — alias survives (separate block)
- Two adjacent recipes where the first is removed — second's body intact
- Recipe with blank lines in the body — body blank lines removed with recipe
- Module-level ``set`` line — survives regardless
- Recipe with parameters — ``migrate msg=""`` — handled correctly
"""

from __future__ import annotations

from pathlib import Path

from zenit.addons.remove import _parse_justfile_blocks, _remove_just_recipes
from zenit.schema.models import EntrySource, Manifest, OwnedEntry

# ── _parse_justfile_blocks unit tests ──────────────────────────────────────────


class TestParseJustfileBlocks:
    """Cover every block kind and the edge cases listed above."""

    def test_simple_recipe(self) -> None:
        lines = ["default:\n", "    @just --list\n"]
        blocks = _parse_justfile_blocks(lines)
        assert len(blocks) == 1
        b = blocks[0]
        assert b.kind == "recipe"
        assert b.recipe_name == "default"
        assert b.lines == lines

    def test_recipe_with_private_attribute(self) -> None:
        lines = ["[private]\n", "build:\n", "    cargo build\n"]
        blocks = _parse_justfile_blocks(lines)
        assert len(blocks) == 1
        b = blocks[0]
        assert b.kind == "recipe"
        assert b.recipe_name == "build"
        assert b.lines == lines  # attribute included in block

    def test_recipe_with_multiple_attributes(self) -> None:
        lines = [
            "[private]\n",
            "[no-exit-message]\n",
            "deploy:\n",
            "    ./deploy.sh\n",
        ]
        blocks = _parse_justfile_blocks(lines)
        assert len(blocks) == 1
        b = blocks[0]
        assert b.kind == "recipe"
        assert b.recipe_name == "deploy"
        assert len(b.lines) == 4

    def test_alias_block(self) -> None:
        lines = ["alias d := docker-up\n"]
        blocks = _parse_justfile_blocks(lines)
        assert len(blocks) == 1
        b = blocks[0]
        assert b.kind == "alias"
        assert b.lines == lines

    def test_setting_block(self) -> None:
        lines = ['set shell := ["bash", "-c"]\n']
        blocks = _parse_justfile_blocks(lines)
        assert len(blocks) == 1
        b = blocks[0]
        assert b.kind == "setting"

    def test_blank_lines(self) -> None:
        lines = ["\n", "\n"]
        blocks = _parse_justfile_blocks(lines)
        assert len(blocks) == 2
        assert all(b.kind == "blank" for b in blocks)

    def test_comment_line(self) -> None:
        lines = ["# this is a comment\n"]
        blocks = _parse_justfile_blocks(lines)
        assert len(blocks) == 1
        assert blocks[0].kind == "other"

    def test_two_adjacent_recipes(self) -> None:
        lines = [
            "build:\n",
            "    cargo build\n",
            "\n",
            "test:\n",
            "    cargo test\n",
        ]
        blocks = _parse_justfile_blocks(lines)
        assert len(blocks) == 2
        assert blocks[0].kind == "recipe"
        assert blocks[0].recipe_name == "build"
        assert blocks[1].kind == "recipe"
        assert blocks[1].recipe_name == "test"

    def test_recipe_with_blank_lines_in_body(self) -> None:
        lines = [
            "test:\n",
            "    echo hello\n",
            "\n",
            "    echo world\n",
        ]
        blocks = _parse_justfile_blocks(lines)
        assert len(blocks) == 1
        b = blocks[0]
        assert b.kind == "recipe"
        assert b.recipe_name == "test"
        assert len(b.lines) == 4  # blank line inside body preserved

    def test_mixed_file(self) -> None:
        lines = [
            'set shell := ["bash", "-c"]\n',
            "\n",
            "alias d := docker-up\n",
            "\n",
            "[private]\n",
            "build:\n",
            "    cargo build\n",
            "\n",
            "# A comment\n",
            "test:\n",
            "    cargo test\n",
        ]
        blocks = _parse_justfile_blocks(lines)
        kinds = [b.kind for b in blocks]
        assert kinds == [
            "setting",
            "blank",
            "alias",
            "blank",
            "recipe",
            "other",
            "recipe",
        ]
        # recipe blocks have correct names
        recipe_blocks = [b for b in blocks if b.kind == "recipe"]
        assert recipe_blocks[0].recipe_name == "build"
        assert recipe_blocks[1].recipe_name == "test"

    def test_recipe_with_dash_in_name(self) -> None:
        lines = ["docker-up:\n", "    docker compose up\n"]
        blocks = _parse_justfile_blocks(lines)
        assert len(blocks) == 1
        assert blocks[0].kind == "recipe"
        assert blocks[0].recipe_name == "docker-up"


# ── _remove_just_recipes unit tests ────────────────────────────────────────────


class TestRemoveJustRecipes:
    """End-to-end removal via ``_remove_just_recipes``."""

    def _make_manifest(self, recipe_names: list[str], addon: str = "test") -> Manifest:
        m = Manifest()
        for name in recipe_names:
            m.just_recipes.append(
                OwnedEntry(name=name, source=EntrySource.ADDON, addon=addon)
            )
        return m

    def test_removes_simple_recipe(self, tmp_path: Path) -> None:
        justfile = tmp_path / "justfile"
        text = "default:\n    @just --list\n"
        justfile.write_text(text)
        manifest = self._make_manifest(["default"])

        result = _remove_just_recipes(tmp_path, manifest, "test")

        assert result == ["default"]
        assert justfile.read_text() == ""

    def test_leaves_other_recipes(self, tmp_path: Path) -> None:
        justfile = tmp_path / "justfile"
        text = "build:\n    cargo build\n\ntest:\n    cargo test\n"
        justfile.write_text(text)
        manifest = self._make_manifest(["build"])

        result = _remove_just_recipes(tmp_path, manifest, "test")

        assert result == ["build"]
        assert justfile.read_text() == "test:\n    cargo test\n"

    def test_removes_recipe_with_private_attribute(self, tmp_path: Path) -> None:
        justfile = tmp_path / "justfile"
        text = "[private]\nbuild:\n    cargo build\n\ntest:\n    cargo test\n"
        justfile.write_text(text)
        manifest = self._make_manifest(["build"])

        result = _remove_just_recipes(tmp_path, manifest, "test")

        assert result == ["build"]
        remaining = justfile.read_text()
        assert "[private]" not in remaining
        assert "build" not in remaining

    def test_removes_recipe_with_multiple_attributes(self, tmp_path: Path) -> None:
        justfile = tmp_path / "justfile"
        text = (
            "[private]\n"
            "[no-exit-message]\n"
            "deploy:\n"
            "    ./deploy.sh\n"
            "\n"
            "test:\n"
            "    cargo test\n"
        )
        justfile.write_text(text)
        manifest = self._make_manifest(["deploy"])

        result = _remove_just_recipes(tmp_path, manifest, "test")

        assert result == ["deploy"]
        remaining = justfile.read_text()
        assert "[private]" not in remaining
        assert "[no-exit-message]" not in remaining
        assert "deploy" not in remaining
        assert "cargo test" in remaining

    def test_alias_survives_removed_recipe(self, tmp_path: Path) -> None:
        justfile = tmp_path / "justfile"
        text = "alias d := docker-up\n\ndocker-up:\n    docker compose up\n"
        justfile.write_text(text)
        manifest = self._make_manifest(["docker-up"])

        result = _remove_just_recipes(tmp_path, manifest, "test")

        assert result == ["docker-up"]
        assert "alias d := docker-up" in justfile.read_text()

    def test_setting_survives(self, tmp_path: Path) -> None:
        justfile = tmp_path / "justfile"
        text = 'set shell := ["bash", "-c"]\n\ndo_stuff:\n    echo hi\n'
        justfile.write_text(text)
        manifest = self._make_manifest(["do_stuff"])

        result = _remove_just_recipes(tmp_path, manifest, "test")

        assert result == ["do_stuff"]
        assert "set shell" in justfile.read_text()

    def test_recipe_with_blank_lines_in_body(self, tmp_path: Path) -> None:
        justfile = tmp_path / "justfile"
        text = "test:\n    echo hello\n\n    echo world\n"
        justfile.write_text(text)
        manifest = self._make_manifest(["test"])

        result = _remove_just_recipes(tmp_path, manifest, "test")

        assert result == ["test"]
        assert justfile.read_text() == ""

    def test_two_adjacent_recipes_first_removed(self, tmp_path: Path) -> None:
        justfile = tmp_path / "justfile"
        text = "build:\n    cargo build\n\ntest:\n    cargo test\n"
        justfile.write_text(text)
        manifest = self._make_manifest(["build"])

        result = _remove_just_recipes(tmp_path, manifest, "test")

        assert result == ["build"]
        assert justfile.read_text() == "test:\n    cargo test\n"

    def test_recipe_with_params(self, tmp_path: Path) -> None:
        justfile = tmp_path / "justfile"
        text = 'migrate: msg=""\n    alembic upgrade head\n'
        justfile.write_text(text)
        manifest = self._make_manifest(["migrate"])

        result = _remove_just_recipes(tmp_path, manifest, "test")

        assert result == ["migrate"]
        assert justfile.read_text() == ""

    def test_removes_nonexistent_recipe_leaves_file(self, tmp_path: Path) -> None:
        justfile = tmp_path / "justfile"
        text = "build:\n    cargo build\n"
        justfile.write_text(text)
        manifest = self._make_manifest(["nonexistent"])

        result = _remove_just_recipes(tmp_path, manifest, "test")

        assert result == ["nonexistent"]
        assert justfile.read_text() == text

    def test_no_justfile_returns_empty(self, tmp_path: Path) -> None:
        manifest = self._make_manifest(["build"])
        result = _remove_just_recipes(tmp_path, manifest, "test")
        assert result == []

    def test_different_addon_not_affected(self, tmp_path: Path) -> None:
        justfile = tmp_path / "justfile"
        text = "a:\n    echo a\n\nb:\n    echo b\n"
        justfile.write_text(text)
        manifest = Manifest()
        manifest.just_recipes.append(
            OwnedEntry(name="a", source=EntrySource.ADDON, addon="addon_a")
        )
        manifest.just_recipes.append(
            OwnedEntry(name="b", source=EntrySource.ADDON, addon="addon_b")
        )

        result = _remove_just_recipes(tmp_path, manifest, "addon_a")

        assert result == ["a"]
        assert "b:" in justfile.read_text()
