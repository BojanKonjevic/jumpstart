from pathlib import Path

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
            volumes=["./.pgdata:/var/lib/postgresql/data"],
            healthcheck={
                "test": ["CMD-SHELL", "pg_isready -U postgres"],
                "interval": "5s",
                "timeout": "5s",
                "retries": 5,
            },
        ),
    ],
    compose_volumes=[".pgdata"],
    env_vars=[
        EnvVar(
            key="DATABASE_URL",
            default="postgresql+asyncpg://postgres:postgres@localhost:5432/(( pkg_name ))",
        ),
    ],
    deps=[
        "asyncpg",
    ],
    just_recipes=[
        '[% if "docker" in addons %]# wait until postgres is ready\nwait-db:\n    uv run python scripts/wait_db.py\n[% endif %]',
        '[% if "docker" in addons %]# start db container, create databases, run migrations\ndb-create:\n    docker compose up -d db\n    just wait-db\n    docker compose exec db createdb -U postgres (( pkg_name ))\n    docker compose exec db createdb -U postgres (( pkg_name ))_test\n    just upgrade\n[% endif %]',
        '[% if "docker" in addons %]# drop and recreate both databases\ndb-reset:\n    docker compose exec db dropdb -U postgres --if-exists (( pkg_name ))\n    docker compose exec db dropdb -U postgres --if-exists (( pkg_name ))_test\n    just db-create\n[% endif %]',
    ],
    injections=[
        Injection(
            point="settings_fields",
            content='    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/(( pkg_name ))"',
        ),
    ],
)
