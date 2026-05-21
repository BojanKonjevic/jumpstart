from __future__ import annotations

import re
from pathlib import Path

from zenit.core.handlers.base import FileHandler
from zenit.schema.models import ManifestBlock

_RECIPE_NAME_RE = re.compile(r"^([a-zA-Z0-9_-]+)\s*:", re.MULTILINE)


class JustfileHandler(FileHandler):
    """Handles justfiles — matched by filename, not suffix."""

    def can_handle(self, path: Path) -> bool:
        return path.name == "justfile"

    def apply(
        self,
        file: Path,
        content: str,
        locator_name: str,
        locator_args: dict[str, object],
    ) -> tuple[str, int, int]:
        source = file.read_text(encoding="utf-8") if file.exists() else ""
        lines = source.splitlines(keepends=True)

        content_lines = content.splitlines(keepends=True)
        if content_lines and not content_lines[-1].endswith("\n"):
            content_lines[-1] += "\n"

        # Duplicate-skip: check if any recipe name from content already exists
        def _recipe_names(ls: list[str]) -> set[str]:
            names: set[str] = set()
            for ln in ls:
                stripped = ln.rstrip()
                if (
                    stripped
                    and not stripped.startswith(" ")
                    and not stripped.startswith("\t")
                    and not stripped.startswith("#")
                ):
                    name = stripped.split(":")[0].strip().lstrip("@")
                    if name:
                        names.add(name)
            return names

        existing_recipes = _recipe_names(lines)
        incoming_recipes = _recipe_names(content_lines)
        if incoming_recipes & existing_recipes:
            end = len(lines)
            return source, end, end

        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"

        start_line = len(lines) + 1
        end_line = start_line + len(content_lines) - 1

        new_source = "".join(lines + content_lines)
        file.write_text(new_source, encoding="utf-8")
        return new_source, start_line, end_line

    def remove(self, file: Path, block: ManifestBlock) -> None:
        if not file.exists():
            return
        source = file.read_text(encoding="utf-8")
        lines = source.splitlines(keepends=True)

        start_str, end_str = block.lines.split("-")
        s = int(start_str) - 1
        e = int(end_str) - 1

        if e >= len(lines):
            return

        new_lines = lines[:s] + lines[e + 1 :]
        file.write_text("".join(new_lines), encoding="utf-8")
