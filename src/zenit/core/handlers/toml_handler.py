from __future__ import annotations

from pathlib import Path

import tomlkit

from zenit.core.handlers.base import FileHandler


class TomlHandler(FileHandler):
    """Handles .toml files — uses tomlkit for round-trip fidelity."""

    def can_handle(self, path: Path) -> bool:
        return path.suffix == ".toml"

    def apply(
        self,
        file: Path,
        content: str,
        locator_name: str,
        locator_args: dict[str, object],
    ) -> tuple[str, int, int]:
        def _dedup(lines: list[str], content_lines: list[str]) -> bool:
            try:
                existing = tomlkit.parse("".join(lines))
                incoming = tomlkit.parse("".join(content_lines))
                return any(k in existing for k in incoming)
            except tomlkit.exceptions.TOMLKitError:
                return False

        return self._append_text(file, content, dedup_check=_dedup)
