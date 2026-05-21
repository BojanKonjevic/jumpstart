"""Helper to dynamically load an `apply()` function from a Python file."""

import importlib.util
from collections.abc import Callable
from pathlib import Path

from zenit.core.context import Context


def load_apply(path: Path) -> Callable[[Context], None]:
    spec = importlib.util.spec_from_file_location("apply", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.apply  # type: ignore[no-any-return]
