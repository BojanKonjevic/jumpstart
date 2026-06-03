import subprocess
from pathlib import Path

from zenit.cli.ui import spinner, warn


def init(project_dir: Path) -> None:
    """Initialise a git repository (best-effort — failure is not fatal).

    If the project already has commits (e.g. from Copier ``_tasks`` that
    ran ``git init && git commit`` before zenit's pipeline finished) the
    existing commit is amended to include any new files and its message
    is normalised to ``"Initial commit"``.
    """
    try:
        with spinner("Initialising git repository"):

            def run(*cmd: str) -> None:
                subprocess.run(
                    list(cmd), cwd=project_dir, check=True, capture_output=True
                )

            run("git", "init")

            # Set a temporary identity if none is configured globally.
            # git init picks up global user.name/email, but CI lacks it.
            try:
                run("git", "config", "user.email")
            except subprocess.CalledProcessError:
                run("git", "config", "user.email", "zenit@localhost")
                run("git", "config", "user.name", "zenit")

            run("git", "add", ".")

            try:
                run("git", "rev-parse", "HEAD")
                run(
                    "git", "commit", "--amend", "--reset-author", "-m", "Initial commit"
                )
            except subprocess.CalledProcessError:
                run("git", "commit", "-m", "Initial commit")
    except Exception as exc:
        warn(f"Git initialisation skipped ({exc}). Project files are still valid.")
        warn("Run 'git init && git add . && git commit' manually when ready.")
