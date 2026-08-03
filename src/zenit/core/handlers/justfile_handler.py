from __future__ import annotations

from pathlib import Path

from zenit.core.handlers.base import FileHandler


class JustfileHandler(FileHandler):
    """Handles justfiles - matched by filename, not suffix."""

    def can_handle(self, path: Path) -> bool:
        return path.name == "justfile"

    def apply(
        self,
        file: Path,
        content: str,
        locator_name: str,
        locator_args: dict[str, object],
    ) -> tuple[str, int, int]:
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

        def _dedup(lines: list[str], content_lines: list[str]) -> bool:
            existing_recipes = _recipe_names(lines)
            incoming_recipes = _recipe_names(content_lines)
            return bool(incoming_recipes & existing_recipes)

        return self._append_text(file, content, dedup_check=_dedup)
