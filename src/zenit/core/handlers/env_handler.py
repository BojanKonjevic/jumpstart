from __future__ import annotations

from pathlib import Path

from zenit.core.handlers.base import FileHandler
from zenit.schema.models import ManifestBlock


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

        content_lines = content.splitlines(keepends=True)
        if content_lines and not content_lines[-1].endswith("\n"):
            content_lines[-1] += "\n"

        # skip lines already present (duplicate-safe)
        existing_keys = {
            ln.split("=")[0].strip()
            for ln in lines
            if "=" in ln and not ln.startswith("#")
        }
        new_lines = [
            ln for ln in content_lines if ln.split("=")[0].strip() not in existing_keys
        ]

        if not new_lines:
            # nothing to add — return current end as the "block"
            end = len(lines)
            return source, end, end

        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"

        start_line = len(lines) + 1
        end_line = start_line + len(new_lines) - 1

        new_source = "".join(lines + new_lines)
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
