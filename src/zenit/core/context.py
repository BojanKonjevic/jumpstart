"""Runtime state passed through the entire scaffold pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from zenit.core.filesystem import FileSystem, RealFileSystem, RecordingFileSystem


@dataclass
class Context:
    """Runtime state passed through the entire scaffold pipeline.

    Filesystem operations are delegated to a ``FileSystem`` instance.
    By default a ``RealFileSystem`` is used.  Pass ``RecordingFileSystem``
    for dry-run mode.
    """

    name: str
    pkg_name: str
    template: str
    addons: list[str]
    zenit_root: Path
    project_dir: Path
    _fs: FileSystem | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._fs is None:
            self._fs = RealFileSystem(self.project_dir)

    @property
    def dry_run(self) -> bool:
        return isinstance(self._fs, RecordingFileSystem)

    def has(self, addon: str) -> bool:
        return addon in self.addons

    # ── Filesystem delegation ─────────────────────────────────────────────────

    def write_file(self, path: str, content: str) -> None:
        self._fs.write_file(path, content)  # type: ignore[union-attr]

    def create_dir(self, path: str) -> None:
        self._fs.create_dir(path)  # type: ignore[union-attr]

    def copy_file(self, src: Path, dest_relative: str) -> None:
        self._fs.copy_file(src, dest_relative)  # type: ignore[union-attr]

    def append_to_file(self, path: str, content: str) -> None:
        self._fs.append_to_file(path, content)  # type: ignore[union-attr]

    def record_modification(self, path: str, description: str) -> None:
        self._fs.record_modification(path, description)  # type: ignore[union-attr]

    def execute_command(self, cmd: list[str], check: bool = True) -> None:
        self._fs.execute_command(cmd, check=check)  # type: ignore[union-attr]
