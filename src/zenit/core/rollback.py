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
def _snapshot_on_failure(
    project_dir: Path,
    label: str,
) -> Generator[Path, None]:
    """Core context: snapshot *project_dir*, restore on any failure.

    Yields the snapshot path.  On success the snapshot is discarded; on
    exception / ``KeyboardInterrupt`` / ``SystemExit`` the project
    directory is restored from the snapshot.
    """
    with tempfile.TemporaryDirectory() as tmp:
        snapshot = Path(tmp) / "snapshot"
        shutil.copytree(project_dir, snapshot, ignore=_SNAPSHOT_IGNORE)
        try:
            yield snapshot
        except BaseException:
            _restore_snapshot(snapshot, project_dir)
            raise


@contextmanager
def addon_or_rollback(project_dir: Path, addon_id: str) -> Generator[None]:
    """Roll back files written by an addon if it fails or is interrupted.

    Uses ``shutil.copytree`` to snapshot the project directory into a temp
    directory.  Generated/cache directories (``.venv``, ``.git``,
    ``__pycache__``, etc.) are excluded from the snapshot via ignore
    patterns since addons never modify them — this eliminates the dominant
    performance bottleneck (copying a virtualenv can take seconds).

    On rollback, files are merged back from the snapshot (overwriting
    modifications) and any new files created by the addon are removed.
    Pre-existing ignored directories are left intact.
    """
    with _snapshot_on_failure(project_dir, f"addon '{addon_id}'"):
        try:
            yield
        except KeyboardInterrupt:
            warn(f"Interrupted — rolled back addon '{addon_id}'.")
            raise
        except (Exception, SystemExit) as exc:
            if not isinstance(exc, SystemExit):
                error(f"Addon '{addon_id}' failed: {exc}")
            warn("Rolled back — no changes were made.")
            raise SystemExit(1) from exc


@contextmanager
def batch_snapshot(project_dir: Path, label: str = "operation") -> Generator[None]:
    """Snapshot the project and roll back everything if the batch fails.

    Wraps a batch of changes (e.g. multiple addon installs) so that if
    *any* step fails, the entire project is restored to its pre-batch
    state.  Uses the same snapshot/restore mechanism as
    ``addon_or_rollback``.
    """
    with _snapshot_on_failure(project_dir, label):
        try:
            yield
        except KeyboardInterrupt:
            warn(f"Interrupted — rolled back batch '{label}'.")
            raise
        except (Exception, SystemExit) as exc:
            if not isinstance(exc, SystemExit):
                error(f"Batch '{label}' failed: {exc}")
            warn("Rolled back — no changes were made.")
            raise SystemExit(1) from exc


# ── Snapshot ignore patterns ──────────────────────────────────────────────────
# These directories are never modified by addons.  Excluding them from the
# snapshot eliminates the dominant performance bottleneck (copying a large
# virtualenv or .git directory can take seconds).
# _SNAPSHOT_EXCLUDE_DIRS is the single source of truth for directory-name
# patterns; _SNAPSHOT_IGNORE adds the glob pattern for egg-info directories.

_SNAPSHOT_EXCLUDE_DIRS = frozenset(
    {
        ".venv",
        "venv",
        "env",
        ".git",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        "node_modules",
        ".eggs",
    }
)

_SNAPSHOT_IGNORE = shutil.ignore_patterns(*_SNAPSHOT_EXCLUDE_DIRS, "*.egg-info")


def _is_excluded_dir(name: str) -> bool:
    return name in _SNAPSHOT_EXCLUDE_DIRS or name.endswith(".egg-info")


def _restore_snapshot(snapshot: Path, target: Path) -> None:
    """Merge *snapshot* back into *target*.

    * Overwrites files that were modified (present in both trees).
    * Removes files/directories that were created by the addon.
    * Leaves pre-existing ignored directories (``.venv``, ``.git``, etc.)
      untouched.
    """
    original_cwd = _move_cwd_out_of_tree(target)
    shutil.copytree(snapshot, target, dirs_exist_ok=True)
    _remove_orphans(snapshot, target)
    if original_cwd is not None:
        os.chdir(original_cwd if original_cwd.exists() else target)


def _remove_orphans(reference: Path, target: Path) -> None:
    """Remove items in *target* that are not in *reference*.

    Recurses into directories present in both trees.  Items whose name
    matches ``_is_excluded_dir`` are never removed since they were excluded
    from the snapshot at copy time.
    """
    ref_names = {p.name for p in reference.iterdir()} if reference.exists() else set()
    for item in list(target.iterdir()):
        if item.is_dir() and _is_excluded_dir(item.name):
            continue
        if item.name not in ref_names:
            if item.is_dir():
                shutil.rmtree(item, ignore_errors=True)
            else:
                item.unlink()
        elif item.is_dir():
            ref_item = reference / item.name
            if ref_item.is_dir():
                _remove_orphans(ref_item, item)


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
