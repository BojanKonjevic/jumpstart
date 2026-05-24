"""Append new just recipes to an existing justfile.

Only appends recipes whose name is not already present in the file.
Preserves all existing content and formatting exactly.
"""

from __future__ import annotations

import re
from pathlib import Path

from zenit.core._filenames import JUSTFILE_NAME
from zenit.core.constants import _recipe_name


def inject_just_recipes(project_dir: Path, recipes: list[str]) -> list[str]:
    """Append missing recipes to the justfile in *project_dir*.

    Returns the list of recipe names that were actually added.
    Recipes whose name already appears in the justfile are skipped.
    """
    justfile_path = project_dir / JUSTFILE_NAME
    if not justfile_path.exists():
        return []

    existing_text = justfile_path.read_text(encoding="utf-8")
    existing_names = _extract_recipe_names(existing_text)

    to_add = [r for r in recipes if r.strip() and _recipe_name(r) not in existing_names]
    if not to_add:
        return []

    appended = existing_text.rstrip("\n") + "\n"
    for recipe in to_add:
        appended += "\n" + recipe.strip("\n") + "\n"

    justfile_path.write_text(appended, encoding="utf-8")
    return [name for r in to_add if (name := _recipe_name(r)) is not None]


def _extract_recipe_names(text: str) -> set[str]:
    """Return all recipe names defined in an existing justfile."""
    names: set[str] = set()
    for line in text.splitlines():
        # Recipe lines start at column 0, are not indented, not comments,
        # and contain a colon. This matches: `run:`, `migrate msg="":`, etc.
        if line and not line[0].isspace() and not line.startswith("#") and ":" in line:
            name = line.split(":")[0].strip().split()[0]
            if name and re.match(r"^[a-zA-Z0-9_-]+$", name):
                names.add(name)
    return names
