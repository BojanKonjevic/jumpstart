from __future__ import annotations

from pathlib import Path

from zenit.core.filesystem import atomic_write_text
from zenit.core.handlers.base import FileHandler, _ensure_trailing_newline


class EnvHandler(FileHandler):
    """Handles .env and .env.example files — line-based key=value."""

    def can_handle(self, path: Path) -> bool:
        return path.name.startswith(".env")

    def apply(
        self,
        file: Path,
        content: str,
        locator_name: str,
        locator_args: dict[str, object],
    ) -> tuple[str, int, int]:
        source = file.read_text(encoding="utf-8") if file.exists() else ""
        lines = source.splitlines(keepends=True)

        content_lines = _ensure_trailing_newline(content.splitlines(keepends=True))

        existing_keys = {
            ln.split("=", 1)[0].strip()
            for ln in lines
            if "=" in ln and not ln.strip().startswith("#")
        }
        new_lines = [
            ln for ln in content_lines if ln.split("=")[0].strip() not in existing_keys
        ]

        if not new_lines:
            end = len(lines)
            return source, end, end

        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"

        start_line = len(lines) + 1
        end_line = start_line + len(new_lines) - 1

        new_source = "".join(lines + new_lines)
        atomic_write_text(file, new_source)
        return new_source, start_line, end_line
