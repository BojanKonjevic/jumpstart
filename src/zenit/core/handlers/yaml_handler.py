from __future__ import annotations

from pathlib import Path

from zenit.core.handlers.base import FileHandler
from zenit.schema.models import ManifestBlock


class YamlHandler(FileHandler):
    """Handles .yml / .yaml files (docker-compose services, volumes, etc.)."""

    def can_handle(self, path: Path) -> bool:
        return path.suffix in {".yml", ".yaml"}

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

        # Duplicate-skip: check if first non-empty content line already appears
        first_key = next(
            (ln.split(":")[0].strip() for ln in content_lines if ln.strip()), None
        )
        if first_key and any(ln.split(":")[0].strip() == first_key for ln in lines):
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
