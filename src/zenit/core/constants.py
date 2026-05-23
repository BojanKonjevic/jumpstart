from __future__ import annotations

import re

_RECIPE_NAME_RE = re.compile(r"^([a-zA-Z0-9_-]+)\s*:", re.MULTILINE)

DEFAULT_DEV_DEPS: list[str] = [
    "pytest>=8",
    "pytest-cov",
    "pytest-asyncio",
    "httpx",
    "mypy",
    "ruff>=0.4",
    "ipython",
]
