from __future__ import annotations

ENV_FILES: tuple[str, ...] = (".env", ".env.example")
COMPOSE_FILE: str = "compose.yml"
PYPROJECT_FILE: str = "pyproject.toml"
JUSTFILE_NAME: str = "justfile"
LOCKFILE_NAME: str = ".zenit.toml"
COMMON_FILES: list[str] = [".gitignore", ".gitattributes", ".pre-commit-config.yaml"]
