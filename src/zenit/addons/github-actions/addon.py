from pathlib import Path

from zenit.core.lockfile import ZenitLockfile
from zenit.schema.models import AddonConfig, FileContribution

_HERE = Path(__file__).parent.absolute()

config = AddonConfig(
    id="github-actions",
    description="CI workflow (lint, type-check, test on push/PR)",
    requires=[],
    files=[
        FileContribution(
            dest=".github/workflows/ci.yml",
            source=str(_HERE / "files" / "ci.yml.j2"),
            template=True,
        ),
    ],
)


def can_apply(project_dir: Path, lockfile: ZenitLockfile) -> str | None:
    # Don't overwrite an existing CI workflow.
    ci_file = project_dir / ".github" / "workflows" / "ci.yml"
    if ci_file.exists():
        return (
            ".github/workflows/ci.yml already exists.\n"
            "    Remove it first if you want zenit to generate a fresh one:\n"
            "      rm .github/workflows/ci.yml"
        )

    # Warn if other workflow files exist — not a blocker, but worth knowing.
    workflows_dir = project_dir / ".github" / "workflows"
    if workflows_dir.is_dir() and any(workflows_dir.iterdir()):
        existing = [f.name for f in workflows_dir.iterdir()]
        existing_str = ", ".join(existing)
        return (
            f"Existing workflow files found in .github/workflows/: {existing_str}\n"
            "    zenit generates ci.yml specifically. If those files conflict, remove them first.\n"
            "    If they don't conflict, remove them and re-add them after running zenit add."
        )

    return None
