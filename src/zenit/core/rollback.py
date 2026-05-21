import os
import shutil
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from zenit.cli.ui import error, warn


@contextmanager
def scaffold_or_rollback(project_dir: Path) -> Generator[None]:
    """Context manager that removes *project_dir* if the scaffold fails.

    On ``KeyboardInterrupt`` the directory is cleaned up and the interrupt is
    re-raised.  On any other exception the directory is cleaned up and the
    process exits with code 1.
    """
    try:
        yield
    except KeyboardInterrupt:
        _cleanup(project_dir)
        warn("Interrupted — removed partial directory.")
        raise
    except (Exception, SystemExit) as exc:
        _cleanup(project_dir)
        if not isinstance(exc, SystemExit):
            error(f"Scaffold failed: {exc}")
        warn("Rolled back — no directory was left behind.")
        raise SystemExit(1) from exc


def _cleanup(project_dir: Path) -> None:
    if project_dir.exists():
        os.chdir(project_dir.parent)
        shutil.rmtree(project_dir, ignore_errors=True)


@contextmanager
def addon_or_rollback(project_dir: Path, addon_id: str) -> Generator[None]:
    """Roll back files written by an addon if it fails or is interrupted."""
    files_before: set[Path] = set()
    content_before: dict[Path, bytes] = {}
    for p in project_dir.rglob("*"):
        files_before.add(p)
        if p.is_file():
            content_before[p] = p.read_bytes()
    try:
        yield
    except KeyboardInterrupt:
        _restore_files(content_before)
        _remove_new_files(project_dir, files_before)
        warn(f"Interrupted — rolled back addon '{addon_id}'.")
        raise
    except (Exception, SystemExit) as exc:
        _restore_files(content_before)
        _remove_new_files(project_dir, files_before)
        if not isinstance(exc, SystemExit):
            error(f"Addon '{addon_id}' failed: {exc}")
        warn("Rolled back — no changes were made.")
        raise SystemExit(1) from exc


def _restore_files(content_before: dict[Path, bytes]) -> None:
    """Restore backed-up file contents, recreating parent dirs if needed."""
    for path, content in content_before.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


def _remove_new_files(project_dir: Path, files_before: set[Path]) -> None:
    files_after = set(project_dir.rglob("*"))
    for f in files_after - files_before:
        if f.is_file():
            f.unlink()
    # prune empty dirs that didn't exist before
    for f in sorted(files_after - files_before, reverse=True):
        if f.is_dir() and not any(f.iterdir()):
            f.rmdir()
