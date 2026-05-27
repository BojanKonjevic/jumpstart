from __future__ import annotations

import re

_RECIPE_NAME_RE = re.compile(r"^([a-zA-Z0-9_-]+)\s*[^:]*:", re.MULTILINE)
_RECIPE_LINE_RE = re.compile(r"^(@?[a-zA-Z0-9_-]+)(?:\s+[^:]+)?:")


def extract_recipe_name(text: str) -> str | None:
    """Return the bare recipe name from a justfile recipe block or line.
    Returns ``None`` for comments, attributes, and other non-recipe content.
    Accepts both single lines and multi-line recipe blocks.
    """
    for raw_line in text.strip().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        m = _RECIPE_LINE_RE.match(line)
        if m:
            return m.group(1).lstrip("@")
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
