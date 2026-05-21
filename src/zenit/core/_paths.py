"""Centralised location for the zenit package root."""

import os
from pathlib import Path


def get_zenit_root() -> Path:
    """Return the filesystem root of the zenit package.

    The environment variable ``ZENIT_ROOT`` takes priority.  When unset
    (the common case), the parent directory of *this module* is used.
    """
    return Path(os.environ.get("ZENIT_ROOT", Path(__file__).parent.parent))
