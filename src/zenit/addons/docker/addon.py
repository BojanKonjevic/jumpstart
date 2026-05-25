from pathlib import Path

from zenit.addons._registry import get_addon
from zenit.core._filenames import COMPOSE_FILE
from zenit.core.apply import merge_compose
from zenit.core.collect import collect_all
from zenit.core.context import Context
from zenit.core.filesystem import FileSystem
from zenit.core.lockfile import ZenitLockfile
from zenit.doctor.doctor import HealthIssue, Severity
from zenit.schema.models import AddonConfig, FileContribution
from zenit.templates._load_config import load_template_config

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
    # Runs inside apply_contributions, before write_manifest.
    # compose.yml has already been created by the file-contributions loop
    # and merge_compose at this point, and the manifest entries for compose
    # services are recorded AFTER this hook returns (by record_addon_manifest_entries
    # in the caller), so the manifest stays consistent with compose.yml.
    try:
        template_config = load_template_config(ctx.zenit_root, ctx.template)
    except (FileNotFoundError, Exception):
        # Copier templates (URIs) cannot be loaded as native configs.
        # Fall back to an empty config — compose contributions are
        # still applied via the addon's own contributions.
        template_config = None
    if template_config is None:
        return
    active_configs = [get_addon(a) for a in ctx.addons]
    contributions = collect_all(template_config, active_configs)
    if not contributions.compose_services and not contributions.compose_volumes:
        return
    compose_path = ctx.project_dir / COMPOSE_FILE
    if not compose_path.exists():
        return
    merge_compose(
        ctx, fs, contributions.compose_services, contributions.compose_volumes
    )


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
