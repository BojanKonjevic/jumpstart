"""Shared pytest fixtures and helpers."""

from pathlib import Path

import pytest
from click.exceptions import Exit as ClickExit


def raises_exit(code: int = 1) -> pytest.ExceptionInfo[ClickExit]:
    """Context manager that expects a ``typer.Exit(code)`` to be raised."""
    return pytest.raises(ClickExit, match="")


class ExitAssertion:
    """Context manager that asserts a ``typer.Exit(1)`` was raised."""

    def __enter__(self) -> ExitAssertion:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> bool:
        if exc_type is None:
            raise AssertionError(
                "Expected a typer.Exit to be raised but nothing was raised"
            )
        if not issubclass(exc_type, ClickExit):
            return False
        assert isinstance(exc_val, ClickExit)
        assert exc_val.exit_code == 1, f"Expected exit code 1, got {exc_val.exit_code}"
        return True


ZENIT_ROOT = Path(__file__).parent.parent / "src" / "zenit"


def write_test_manifest(
    project_dir: Path,
    addons: list[str],
    render_vars: dict[str, object],
) -> None:
    """Write manifest entries for all *addons* — mirrors real ``zenit add`` flow.

    Call this after ``generate_all()`` in test ``_scaffold`` helpers so that
    ``remove_addon`` can read manifest entries instead of relying on
    ``addon_cfg`` directly.

    Reads any existing manifest (``apply_contributions`` may have already
    recorded ``python_blocks``) and appends addon-owned entries to it.
    """
    from zenit.addons._registry import get_available_addons
    from zenit.core.manifest import (
        read_manifest,
        record_addon_manifest_entries,
        write_manifest,
    )
    from zenit.core.render import make_env

    manifest = read_manifest(project_dir)
    string_env = make_env()
    available = get_available_addons()
    for addon_id in addons:
        cfg = next(c for c in available if c.id == addon_id)
        record_addon_manifest_entries(manifest, cfg, string_env, render_vars)
    write_manifest(project_dir, manifest)
