"""Declarative config for the redis addon."""

from pathlib import Path

from zenit.addons._preflight import (
    reject_existing_file,
    reject_existing_in_env,
    require_src_layout,
)
from zenit.core.lockfile import ZenitLockfile
from zenit.core.pkg_name import normalise_pkg_name
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
    id="redis",
    description="Redis service + connection helper + compose service",
    requires=[],
    files=[
        FileContribution(
            dest="src/{{pkg_name}}/integrations/__init__.py",
            content="",
        ),
        FileContribution(
            dest="src/{{pkg_name}}/integrations/redis.py",
            source=str(_HERE / "files" / "redis.py"),
        ),
    ],
    compose_services=[
        ComposeService(
            name="redis",
            image="redis:7-alpine",
            ports=["6379:6379"],
            volumes=["redis-data:/data"],
            command="redis-server --appendonly yes",
            healthcheck={
                "test": ["CMD", "redis-cli", "ping"],
                "interval": "1s",
                "timeout": "3s",
                "retries": 5,
            },
        )
    ],
    compose_volumes=["redis-data"],
    env_vars=[
        EnvVar(key="REDIS_URL", default="redis://localhost:6379/0"),
    ],
    deps=["redis>=5", "hiredis"],
    dev_deps=["fakeredis"],
    just_recipes=[
        '[% if "docker" in addons %]# start redis\nredis-up:\n    docker compose up -d redis\n[% endif %]',
        '[% if "docker" in addons %]# stop redis\nredis-down:\n    docker compose stop redis\n[% endif %]',
        "# open redis-cli\nredis-cli:\n    redis-cli",
    ],
    injections=[
        Injection(
            point="settings_fields",
            content='    redis_url: str = "redis://localhost:6379/0"',
        ),
    ],
)


def can_apply(project_dir: Path, lockfile: ZenitLockfile) -> str | None:
    pkg_name = normalise_pkg_name(project_dir.name)

    reason = require_src_layout(project_dir, "redis")
    if reason:
        return reason

    redis_file = project_dir / "src" / pkg_name / "integrations" / "redis.py"
    reason = reject_existing_file(redis_file, project_dir)
    if reason:
        return reason

    integrations_dir = project_dir / "src" / pkg_name / "integrations"
    if integrations_dir.is_dir():
        for f in integrations_dir.rglob("*.py"):
            text = f.read_text(encoding="utf-8")
            if "redis" in text.lower():
                return (
                    f"{f.relative_to(project_dir)} already references redis.\n"
                    "    zenit won't overwrite existing redis configuration.\n"
                    "    Review that file and remove any redis references if you want zenit to manage it."
                )

    return reject_existing_in_env(project_dir, "REDIS_URL")


def health_check(project_dir: Path, lockfile: object) -> list[HealthIssue]:

    pkg_name = normalise_pkg_name(project_dir.name)
    issues: list[HealthIssue] = []

    redis_file = project_dir / "src" / pkg_name / "integrations" / "redis.py"
    if not redis_file.exists():
        return issues

    for env_file in (".env", ".env.example"):
        path = project_dir / env_file
        if path.exists():
            if "REDIS_URL=" in path.read_text(encoding="utf-8"):
                issues.append(
                    HealthIssue(Severity.OK, f"REDIS_URL is defined in '{env_file}'.")
                )
            else:
                issues.append(
                    HealthIssue(
                        Severity.WARN,
                        f"REDIS_URL is missing from '{env_file}'.",
                        hint=f"Add 'REDIS_URL=redis://localhost:6379/0' to '{env_file}'.",
                    )
                )

    return issues
