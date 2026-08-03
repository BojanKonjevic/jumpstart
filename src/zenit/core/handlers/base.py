from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path

from zenit.cli.ui import warn
from zenit.core.filesystem import atomic_write_text
from zenit.schema.exceptions import ZenitError
from zenit.schema.models import ManifestBlock


def _ensure_trailing_newline(content_lines: list[str]) -> list[str]:
    """Ensure the last line ends with a newline."""
    if not content_lines or (len(content_lines) == 1 and content_lines[0] == ""):
        return content_lines
    if not content_lines[-1].endswith("\n"):
        result = [*content_lines]
        result[-1] += "\n"
        return result
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
        # Verify the recorded block still matches before deleting
        if block.fingerprint:
            import hashlib

            actual = hashlib.sha256("".join(lines[s : e + 1]).encode()).hexdigest()
            if f"sha256:{actual}" != block.fingerprint:
                warn(
                    f"Block content has changed since injection - "
                    f"cannot safely remove from '{file}'."
                )
                raise ZenitError(
                    f"Block content has changed since injection - "
                    f"cannot safely remove from '{file}'.\n"
                    f"  Expected fingerprint: {block.fingerprint}\n"
                    f"  Actual fingerprint:   sha256:{actual}\n"
                    f"  Manual steps:\n"
                    f"    - Open {file}\n"
                    f"    - Find the code added for point '{block.point}' and remove it\n"
                    f"    - Run: zenit doctor"
                )
        new_lines = lines[:s] + lines[e + 1 :]
        atomic_write_text(file, "".join(new_lines))

    def validate(self, file: Path) -> None:  # noqa: B027
        """Verify the file can still be parsed after removal. No-op in base handler."""

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
        handler = self._get(file)
        handler.remove(file, block)
        handler.validate(file)
