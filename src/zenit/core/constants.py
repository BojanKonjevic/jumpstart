from __future__ import annotations

import re

_RECIPE_NAME_RE = re.compile(r"^([a-zA-Z0-9_-]+)\s*:", re.MULTILINE)


def _recipe_name(recipe: str) -> str | None:
    """Return the bare recipe name from a recipe block string.
    Returns ``None`` when no recipe line is found (comment-only or empty input).
    """
    for line in recipe.strip().splitlines():
        if not line.startswith("#"):
            return line.split(":")[0].strip().split()[0]
    return None


DEFAULT_DEV_DEPS: list[str] = [
    "pytest>=8",
    "pytest-cov",
    "pytest-asyncio",
    "httpx",
    "mypy",
    "ruff>=0.4",
    "ipython",
]
