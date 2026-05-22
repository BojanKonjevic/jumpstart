"""Runtime state passed through the entire scaffold pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class Context:
    """Runtime state passed through the entire scaffold pipeline."""

    name: str
    pkg_name: str
    template: str
    addons: list[str]
    zenit_root: Path
    project_dir: Path
    dry_run: bool = False

    def has(self, addon: str) -> bool:
        return addon in self.addons
