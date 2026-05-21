"""User-level configuration for zenit.

Config file locations (in priority order):
  Linux:          $XDG_CONFIG_HOME/zenit/zenit.toml
                  (defaults to ~/.config/zenit/zenit.toml)
  macOS:          $XDG_CONFIG_HOME/zenit/zenit.toml
                  (defaults to ~/.config/zenit/zenit.toml)
  Windows:        %APPDATA%\\zenit\\zenit.toml
                  (defaults to ~/AppData/Roaming/zenit/zenit.toml)

Example zenit.toml:
    default_template = "fastapi"
    default_addons = ["docker", "github-actions"]
"""

from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ZenitConfig:
    """Parsed user configuration. All fields are optional."""

    default_template: str | None = None
    default_addons: list[str] = field(default_factory=list)


def config_path() -> Path:
    """Return the platform-appropriate config file path.

    Respects XDG_CONFIG_HOME on Linux/macOS.
    Uses %APPDATA% on Windows, falling back to ~/AppData/Roaming.
    """
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
    else:
        # XDG on Linux; macOS doesn't set XDG_CONFIG_HOME by default but
        # respects it if set, otherwise falls back to ~/.config (same as Linux).
        xdg = os.environ.get("XDG_CONFIG_HOME")
        base = Path(xdg) if xdg else Path.home() / ".config"

    return base / "zenit" / "zenit.toml"


def load_config() -> ZenitConfig:
    """Load and return user config. Returns an empty ZenitConfig on any error.

    Failures (file absent, malformed TOML, wrong types) are all silently
    ignored — the tool must always work without a config file.
    """
    path = config_path()
    if not path.exists():
        return ZenitConfig()

    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except Exception:
        return ZenitConfig()

    default_template = data.get("default_template")
    if not isinstance(default_template, str):
        default_template = None

    raw_addons = data.get("default_addons", [])
    if not isinstance(raw_addons, list):
        raw_addons = []
    default_addons = [a for a in raw_addons if isinstance(a, str)]

    return ZenitConfig(
        default_template=default_template,
        default_addons=default_addons,
    )
