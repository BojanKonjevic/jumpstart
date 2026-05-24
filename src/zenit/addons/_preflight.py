"""Shared preflight checks for addon can_apply / can_remove hooks."""

from __future__ import annotations

from pathlib import Path

from zenit.core._filenames import ENV_FILES


def require_src_layout(project_dir: Path, addon_name: str) -> str | None:
    if not (project_dir / "src").is_dir():
        return (
            f"No src/ directory found — {addon_name} addon expects a src layout.\n"
            "    Ensure your package lives under src/<pkg_name>/."
        )
    return None


def reject_existing_file(path: Path, project_dir: Path) -> str | None:
    if path.exists():
        rel = path.relative_to(project_dir)
        return (
            f"{rel} already exists.\n"
            "    Remove it first if you want zenit to generate a fresh one:\n"
            f"      rm {rel}"
        )
    return None


def reject_existing_in_env(
    project_dir: Path, key: str, env_files: tuple[str, ...] = ENV_FILES
) -> str | None:
    for env_file in env_files:
        path = project_dir / env_file
        if path.exists() and key in path.read_text(encoding="utf-8"):
            return (
                f"{key} is already defined in {env_file}.\n"
                "    zenit won't add a duplicate. Remove it first if you want zenit to manage it:\n"
                f"      Remove the {key} line from {env_file}"
            )
    return None
