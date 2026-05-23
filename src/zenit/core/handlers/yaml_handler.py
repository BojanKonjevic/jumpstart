from __future__ import annotations

from pathlib import Path

from zenit.core.handlers.base import FileHandler


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
        def _dedup(lines: list[str], content_lines: list[str]) -> bool:
            first_key = next(
                (ln.split(":")[0].strip() for ln in content_lines if ln.strip()), None
            )
            return bool(
                first_key and any(ln.split(":")[0].strip() == first_key for ln in lines)
            )

        return self._append_text(file, content, dedup_check=_dedup)
