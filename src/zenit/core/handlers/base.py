from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path

from zenit.core.filesystem import atomic_write_text
from zenit.schema.models import ManifestBlock


def _ensure_trailing_newline(content_lines: list[str]) -> list[str]:
    """Ensure the last line ends with a newline."""
    if content_lines and not content_lines[-1].endswith("\n"):
        content_lines[-1] += "\n"
    return content_lines


class FileHandler(ABC):
    """Base class for all file-type handlers."""

    @abstractmethod
    def can_handle(self, path: Path) -> bool: ...

    @abstractmethod
    def apply(
        self,
        file: Path,
        content: str,
        locator_name: str,
        locator_args: dict[str, object],
    ) -> tuple[str, int, int]: ...

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
        atomic_write_text(file, "".join(new_lines))

    def _append_text(
        self,
        file: Path,
        content: str,
        dedup_check: Callable[[list[str], list[str]], bool] | None = None,
    ) -> tuple[str, int, int]:
        source = file.read_text(encoding="utf-8") if file.exists() else ""
        lines = source.splitlines(keepends=True)

        content_lines = _ensure_trailing_newline(content.splitlines(keepends=True))

        if dedup_check is not None and dedup_check(lines, content_lines):
            end = len(lines)
            return source, end, end

        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"

        start_line = len(lines) + 1
        end_line = start_line + len(content_lines) - 1

        new_source = "".join(lines + content_lines)
        atomic_write_text(file, new_source)
        return new_source, start_line, end_line


class HandlerDispatcher:
    """Routes apply/remove calls to the correct FileHandler."""

    def __init__(self) -> None:
        # Import concrete handlers here to avoid circular imports at module level.
        from zenit.core.handlers.env_handler import EnvHandler
        from zenit.core.handlers.justfile_handler import JustfileHandler
        from zenit.core.handlers.python_handler import PythonHandler
        from zenit.core.handlers.toml_handler import TomlHandler
        from zenit.core.handlers.yaml_handler import YamlHandler

        self._handlers: list[FileHandler] = [
            PythonHandler(),
            EnvHandler(),
            YamlHandler(),
            TomlHandler(),
            JustfileHandler(),
        ]

    def _get(self, path: Path) -> FileHandler:
        for handler in self._handlers:
            if handler.can_handle(path):
                return handler
        raise ValueError(f"No handler found for file: {path}")

    def apply(
        self,
        file: Path,
        content: str,
        locator_name: str,
        locator_args: dict[str, object],
    ) -> tuple[str, int, int]:
        return self._get(file).apply(file, content, locator_name, locator_args)

    def remove(self, file: Path, block: ManifestBlock) -> None:
        self._get(file).remove(file, block)
