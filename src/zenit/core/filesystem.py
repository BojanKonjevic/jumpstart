"""FileSystem protocol and implementations — replaces Context inheritance for dry-run."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Protocol


def atomic_write_text(path: Path, content: str, encoding: str = "utf-8") -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.tmp.")
    try:
        os.write(fd, content.encode(encoding))
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)


class FileSystem(Protocol):
    """Protocol for filesystem operations.

    Two implementations: ``RealFileSystem`` (does real I/O) and
    ``RecordingFileSystem`` (records operations for dry-run previews).
    """

    def write_file(self, path: str, content: str) -> None: ...
    def create_dir(self, path: str) -> None: ...
    def copy_file(self, src: Path, dest_relative: str) -> None: ...
    def append_to_file(self, path: str, content: str) -> None: ...
    def execute_command(self, cmd: list[str], check: bool = True) -> None: ...


class RealFileSystem:
    """Real filesystem implementation — performs actual I/O."""

    def __init__(self, project_dir: Path) -> None:
        self._project_dir = project_dir

    def write_file(self, path: str, content: str) -> None:
        dest = self._project_dir / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(dest, content)

    def create_dir(self, path: str) -> None:
        (self._project_dir / path).mkdir(parents=True, exist_ok=True)

    def copy_file(self, src: Path, dest_relative: str) -> None:
        dest = self._project_dir / dest_relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(src, dest)

    def append_to_file(self, path: str, content: str) -> None:
        file_path = self._project_dir / path
        with open(file_path, "a") as f:
            f.write(content)

    def execute_command(self, cmd: list[str], check: bool = True) -> None:
        try:
            subprocess.run(cmd, check=check, capture_output=True)
        except subprocess.CalledProcessError as exc:
            print(f"Command failed: {' '.join(cmd)}", file=sys.stderr)
            if exc.stdout:
                print(exc.stdout.decode(), file=sys.stderr)
            if exc.stderr:
                print(exc.stderr.decode(), file=sys.stderr)
            raise


class RecordingFileSystem:
    """Recording implementation — captures operations without touching disk."""

    def __init__(self, project_dir: Path) -> None:
        self._project_dir = project_dir
        self.recorded_files: list[tuple[str, str, str]] = []

    def write_file(self, path: str, content: str) -> None:
        self.recorded_files.append(("create", path, ""))

    def create_dir(self, path: str) -> None:
        self.recorded_files.append(("mkdir", path, ""))

    def copy_file(self, src: Path, dest_relative: str) -> None:
        self.recorded_files.append(("copy", dest_relative, ""))

    def append_to_file(self, path: str, content: str) -> None:
        preview = content.replace("\n", " ").strip()[:80]
        self.recorded_files.append(("append", path, preview))

    def execute_command(self, cmd: list[str], check: bool = True) -> None:
        return
