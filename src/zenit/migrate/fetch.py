"""Source fetching and normalisation for Copier template migration."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from zenit.schema.exceptions import ZenitError


def _is_github_url(source: str) -> bool:
    return source.startswith("https://github.com/") or source.startswith("gh:")


def _normalise_source(source: str) -> str:
    if source.startswith("gh:"):
        repo = source[3:]
        if "/" not in repo:
            repo = f"{repo}/{repo}"
        return f"https://github.com/{repo}"
    path = Path(source)
    if not str(source).startswith("https://") and not str(source).startswith("http://"):
        return str(path.resolve())
    return source


def _derive_project_name_from_source(source: str) -> str | None:
    name: str | None = None
    if source.startswith("https://github.com/"):
        parts = source.rstrip("/").split("/")
        if parts:
            name = parts[-1]
    elif source.startswith("gh:"):
        parts = source[3:].split("/")
        name = parts[-1] if parts[-1] else None
    elif "://" not in source:
        path = Path(source)
        n = path.name
        if n and n != ".":
            name = n
    if name and name.endswith(".git"):
        name = name[:-4]
    return name


def _pick_project_name(
    project_name_answer: object,
    name_answer: object,
    source: str,
    template_dir: Path,
) -> str:
    candidates: list[str | None] = [
        str(project_name_answer).strip() if project_name_answer else None,
        str(name_answer).strip() if name_answer else None,
        _derive_project_name_from_source(source),
        template_dir.name,
    ]
    for c in candidates:
        if c and c.strip():
            return c.strip()
    return template_dir.name


def _fetch_source(source: str) -> Path:
    normalised = _normalise_source(source)

    if normalised.startswith("https://"):
        tmp = tempfile.mkdtemp(prefix="zenit-migrate-")
        try:
            result = subprocess.run(
                ["git", "clone", "--depth=1", normalised, tmp],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                shutil.rmtree(tmp, ignore_errors=True)
                raise ZenitError(f"Failed to clone template from '{normalised}':\n")
            return Path(tmp)
        except FileNotFoundError:
            shutil.rmtree(tmp, ignore_errors=True)
            raise ZenitError(
                f"git is required to clone '{normalised}'. "
                "Install git and try again, or use a local path."
            ) from None

    path = Path(normalised).resolve()
    if not path.exists():
        raise ZenitError(f"Template path '{path}' does not exist.")
    if not path.is_dir():
        raise ZenitError(f"Template path '{path}' is not a directory.")
    return path


def _cleanup_temp(template_dir: Path) -> None:
    name = template_dir.resolve().name
    if name.startswith("zenit-migrate-"):
        shutil.rmtree(template_dir, ignore_errors=True)
