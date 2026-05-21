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
