"""Package name normalisation."""

from __future__ import annotations

import re


def normalise_pkg_name(project_name: str) -> str:
    name = project_name.lower()
    name = re.sub(r"[^a-z0-9_]", "_", name)
    return name.strip("_")
