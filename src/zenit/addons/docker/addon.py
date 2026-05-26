from pathlib import Path

from zenit.core._filenames import COMPOSE_FILE
from zenit.core.context import Context
from zenit.core.filesystem import FileSystem
from zenit.core.lockfile import ZenitLockfile
from zenit.doctor.doctor import HealthIssue, Severity
from zenit.schema.models import AddonConfig, FileContribution

_HERE = Path(__file__).parent.absolute()

config = AddonConfig(
    id="docker",
    description="Dockerfile + compose.yml + .dockerignore",
    requires=[],
    files=[
        FileContribution(
            dest="Dockerfile",
            source=str(_HERE / "files" / "Dockerfile.j2"),
            template=True,
        ),
        FileContribution(
            dest=COMPOSE_FILE,
            source=str(_HERE / "files" / "compose.yml.j2"),
            template=True,
        ),
        FileContribution(
            dest=".dockerignore",
            source=str(_HERE / "files" / ".dockerignore"),
        ),
    ],
    just_recipes=[
        "# build and start all services\ndocker-up:\n    docker compose up --build",
        "# stop all services\ndocker-down:\n    docker compose down",
    ],
)


def health_check(project_dir: Path, lockfile: ZenitLockfile) -> list[HealthIssue]:
    issues: list[HealthIssue] = []
    if not (project_dir / COMPOSE_FILE).exists():
        issues.append(
            HealthIssue(
                Severity.ERROR,
                "compose.yml is missing but docker addon is installed.",
                "Restore compose.yml or re-run 'zenit add docker'.",
            )
        )
    return issues


def post_apply(ctx: Context, fs: FileSystem) -> None:  # noqa: ARG001
    # Compose merge is fully handled by _refresh_compose in add.py.
    # Docker post_apply is intentionally a no-op for compose — the
    # reconciliation is done once after the full add pipeline completes.
    return


def can_apply(project_dir: Path, lockfile: ZenitLockfile) -> str | None:
    if not (project_dir / "src").is_dir():
        return (
            "No src/ directory found — docker addon expects a src layout.\n"
            "    Ensure your package lives under src/<pkg_name>/."
        )

    if not (project_dir / "pyproject.toml").exists():
        return (
            "No pyproject.toml found — docker addon requires one to exist.\n"
            "    The generated Dockerfile copies pyproject.toml during the build."
        )

    if (project_dir / "Dockerfile").exists():
        return (
            "A Dockerfile already exists in this directory.\n"
            "    Remove it first if you want zenit to generate one:\n"
            "      rm Dockerfile"
        )

    if (project_dir / COMPOSE_FILE).exists():
        return (
            "compose.yml already exists in this directory.\n"
            "    Remove it first if you want zenit to generate one:\n"
            "      rm compose.yml"
        )

    if (project_dir / "docker-compose.yml").exists():
        return (
            "docker-compose.yml already exists in this directory.\n"
            "    zenit generates compose.yml (the modern filename). Remove or rename it first:\n"
            "      mv docker-compose.yml compose.yml  # if you want to keep it\n"
            "      rm docker-compose.yml              # if you want zenit to generate a fresh one"
        )

    return None
