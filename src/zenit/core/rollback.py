import os
import shutil
import tempfile
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
        failed_paths: list[str] = []

        def _onerror(func: object, path: str, exc_info: object) -> None:
            failed_paths.append(path)

        shutil.rmtree(project_dir, onerror=_onerror)
        if failed_paths:
            warn(
                f"Failed to remove {len(failed_paths)} item(s) during cleanup.\n"
                + "\n".join(f"  {p}" for p in failed_paths[:10])
                + (
                    f"\n  … and {len(failed_paths) - 10} more"
                    if len(failed_paths) > 10
                    else ""
                )
                + f"\nPlease remove '{project_dir}' manually:  rm -rf {project_dir}"
            )


@contextmanager
def addon_or_rollback(project_dir: Path, addon_id: str) -> Generator[None]:
    """Roll back files written by an addon if it fails or is interrupted.

    Uses ``shutil.copytree`` to snapshot the project directory into a temp
    directory for O(1) bulk backup/restore instead of per-file IO.
    """
    with tempfile.TemporaryDirectory() as tmp:
        snapshot = Path(tmp) / "snapshot"
        shutil.copytree(project_dir, snapshot)
        try:
            yield
        except KeyboardInterrupt:
            _restore_snapshot(snapshot, project_dir)
            warn(f"Interrupted — rolled back addon '{addon_id}'.")
            raise
        except (Exception, SystemExit) as exc:
            _restore_snapshot(snapshot, project_dir)
            if not isinstance(exc, SystemExit):
                error(f"Addon '{addon_id}' failed: {exc}")
            warn("Rolled back — no changes were made.")
            raise SystemExit(1) from exc


def _restore_snapshot(snapshot: Path, target: Path) -> None:
    original_cwd = _move_cwd_out_of_tree(target)
    shutil.rmtree(target, ignore_errors=True)
    shutil.copytree(snapshot, target)
    if original_cwd is not None:
        os.chdir(original_cwd if original_cwd.exists() else target)


def _move_cwd_out_of_tree(target: Path) -> Path | None:
    """Move cwd to a stable parent if it lives inside *target*.

    ``addon_or_rollback`` removes and recreates the full project directory from
    a snapshot. If the current process stays inside that directory, ``os.getcwd``
    fails until the user manually leaves and re-enters it.
    """
    cwd = Path.cwd().resolve()
    target_resolved = target.resolve()

    if cwd == target_resolved or target_resolved in cwd.parents:
        os.chdir(target.parent)
        return cwd

    return None
