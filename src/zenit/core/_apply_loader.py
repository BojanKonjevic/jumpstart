"""Helper to dynamically load an `apply()` function from a Python file."""

import importlib.util
from collections.abc import Callable
from pathlib import Path

from zenit.core.context import Context
from zenit.core.filesystem import FileSystem
from zenit.schema.exceptions import ZenitError


def load_apply(path: Path) -> Callable[[Context, FileSystem], None]:
    if not path.exists():
        raise ZenitError(f"Failed to load apply module from '{path}': file not found")
    spec = importlib.util.spec_from_file_location("apply", path)
    if spec is None or spec.loader is None:
        raise ZenitError(
            f"Failed to load apply module from '{path}': "
            f"could not find or load the module spec"
        )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.apply  # type: ignore[no-any-return]
