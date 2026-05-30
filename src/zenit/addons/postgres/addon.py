from pathlib import Path

from zenit.addons._preflight import (
    reject_existing_file,
    reject_existing_in_env,
    require_src_layout,
)
from zenit.core._filenames import ENV_FILES, JUSTFILE_NAME
from zenit.core.constants import extract_recipe_name
from zenit.core.lockfile import ZenitLockfile
from zenit.doctor.doctor import HealthIssue, Severity
from zenit.schema.models import (
    AddonConfig,
    ComposeService,
    EnvVar,
    FileContribution,
    Injection,
)

_HERE = Path(__file__).parent.absolute()

config = AddonConfig(
    id="postgres",
    description="PostgreSQL driver + DATABASE_URL + compose service",
    requires=[],
    files=[
        FileContribution(
            dest="scripts/wait_db.py",
            source=str(_HERE / "files" / "scripts" / "wait_db.py"),
        ),
    ],
    compose_services=[
        ComposeService(
            name="db",
            image="postgres:16",
            environment={"POSTGRES_PASSWORD": "postgres"},
            ports=["5432:5432"],
            volumes=["pgdata:/var/lib/postgresql/data"],
            healthcheck={
                "test": ["CMD-SHELL", "pg_isready -U postgres"],
                "interval": "5s",
                "timeout": "5s",
                "retries": 5,
            },
        ),
    ],
    compose_volumes=["pgdata"],
    compose_app_env={
        "DATABASE_URL": "postgresql+asyncpg://postgres:postgres@db:5432/(( pkg_name ))"
    },
    compose_app_depends_on={"db": {"condition": "service_healthy"}},
    env_vars=[
        EnvVar(
            key="DATABASE_URL",
            default="postgresql+asyncpg://postgres:postgres@localhost:5432/(( pkg_name ))",
        ),
    ],
    deps=[
        "asyncpg",
        "python-dotenv",
    ],
    just_recipes=[
        '[% if "docker" in addons %]# wait until postgres is ready\nwait-db:\n    uv run python scripts/wait_db.py\n[% else %]# wait until postgres is ready\nwait-db:\n    pg_isready -U postgres\n[% endif %]',
        '[% if "docker" in addons %]# start db container and create both databases\ndb-create:\n    docker compose up -d db\n    just wait-db\n    docker compose exec db createdb -U postgres (( pkg_name ))\n    docker compose exec db createdb -U postgres (( pkg_name ))_test\n[% else %]# create both databases\ndb-create:\n    just wait-db\n    createdb -U postgres (( pkg_name ))\n    createdb -U postgres (( pkg_name ))_test\n[% endif %]',
        '[% if "docker" in addons %]# drop and recreate both databases\ndb-reset:\n    docker compose exec db dropdb -U postgres --if-exists (( pkg_name ))\n    docker compose exec db dropdb -U postgres --if-exists (( pkg_name ))_test\n    just db-create\n[% else %]# drop and recreate both databases\ndb-reset:\n    dropdb -U postgres --if-exists (( pkg_name ))\n    dropdb -U postgres --if-exists (( pkg_name ))_test\n    just db-create\n[% endif %]',
        '[% if "docker" in addons %]# drop both databases (keeps container running)\ndb-drop:\n    docker compose exec db dropdb -U postgres --if-exists (( pkg_name ))\n    docker compose exec db dropdb -U postgres --if-exists (( pkg_name ))_test\n[% else %]# drop both databases\ndb-drop:\n    dropdb -U postgres --if-exists (( pkg_name ))\n    dropdb -U postgres --if-exists (( pkg_name ))_test\n[% endif %]',
    ],
    injections=[
        Injection(
            point="settings_fields",
            templates=["fastapi"],
            content='    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/(( pkg_name ))"',
        ),
    ],
)


def can_apply(project_dir: Path, lockfile: ZenitLockfile) -> str | None:
    reason = require_src_layout(project_dir, "postgres")
    if reason:
        return reason

    wait_script = project_dir / "scripts" / "wait_db.py"
    reason = reject_existing_file(wait_script, project_dir)
    if reason:
        return reason

    return reject_existing_in_env(project_dir, "DATABASE_URL")


_POSTGRES_RECIPES = frozenset({"wait-db", "db-create", "db-reset", "db-drop"})


def health_check(project_dir: Path, lockfile: object) -> list[HealthIssue]:
    issues: list[HealthIssue] = []

    for env_file in ENV_FILES:
        path = project_dir / env_file
        if path.exists():
            if "DATABASE_URL=" in path.read_text(encoding="utf-8"):
                issues.append(
                    HealthIssue(
                        Severity.OK, f"DATABASE_URL is defined in '{env_file}'."
                    )
                )
            else:
                issues.append(
                    HealthIssue(
                        Severity.WARN,
                        f"DATABASE_URL is missing from '{env_file}'.",
                        hint=f"Add 'DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/<dbname>' to '{env_file}'.",
                    )
                )

    if isinstance(lockfile, ZenitLockfile) and "postgres" in lockfile.addons:
        justfile_path = project_dir / JUSTFILE_NAME
        if justfile_path.exists():
            text = justfile_path.read_text(encoding="utf-8")
            existing = set()
            for line in text.splitlines():
                name = extract_recipe_name(line)
                if name is not None:
                    existing.add(name)
            missing = _POSTGRES_RECIPES - existing
            if missing:
                issues.append(
                    HealthIssue(
                        Severity.WARN,
                        f"Postgres recipes are missing from the justfile: {', '.join(sorted(missing))}.",
                        hint="Run 'zenit add postgres' again, or 'zenit doctor --fix'.",
                    )
                )
            else:
                issues.append(
                    HealthIssue(
                        Severity.OK,
                        "All postgres recipes are present in the justfile.",
                    )
                )

    return issues
