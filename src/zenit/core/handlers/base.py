from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from zenit.schema.models import ManifestBlock


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

    @abstractmethod
    def remove(self, file: Path, block: ManifestBlock) -> None: ...


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
