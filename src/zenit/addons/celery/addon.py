from pathlib import Path

from zenit.core.lockfile import ZenitLockfile
from zenit.core.pkg_name import normalise_pkg_name
from zenit.doctor.doctor import HealthIssue, Severity
from zenit.schema.models import AddonConfig, ComposeService, FileContribution

_HERE = Path(__file__).parent.absolute()

config = AddonConfig(
    id="celery",
    description="Celery worker + beat scheduler, backed by Redis",
    requires=["redis"],
    files=[
        FileContribution(
            dest="src/{{pkg_name}}/tasks/__init__.py",
            content="",
        ),
        FileContribution(
            dest="src/{{pkg_name}}/tasks/celery_app.py",
            source=str(_HERE / "files" / "tasks" / "celery_app.py.j2"),
            template=True,
        ),
        FileContribution(
            dest="src/{{pkg_name}}/tasks/example_tasks.py",
            source=str(_HERE / "files" / "tasks" / "example_tasks.py.j2"),
            template=True,
        ),
    ],
    compose_services=[
        ComposeService(
            name="celery-worker",
            build=".",
            command="celery -A {{pkg_name}}.tasks.celery_app worker --loglevel=info",
            env_file=[".env"],
            environment={"REDIS_URL": "redis://redis:6379/0"},
            depends_on={
                "redis": {"condition": "service_healthy"},
            },
            develop_watch=[{"action": "sync", "path": "./src", "target": "/app/src"}],
        ),
        ComposeService(
            name="celery-beat",
            build=".",
            command="celery -A {{pkg_name}}.tasks.celery_app beat --loglevel=info",
            env_file=[".env"],
            environment={"REDIS_URL": "redis://redis:6379/0"},
            depends_on={
                "redis": {"condition": "service_healthy"},
            },
            develop_watch=[{"action": "sync", "path": "./src", "target": "/app/src"}],
        ),
    ],
    deps=["celery[redis]>=5", "flower"],
    dev_deps=["pytest-celery"],
    just_recipes=[
        '[% if "docker" in addons %]'
        "# start celery worker and beat scheduler\n"
        "celery-up:\n"
        "    docker compose up -d celery-worker celery-beat\n"
        "[% endif %]",
        '[% if "docker" in addons %]'
        "# stop celery worker and beat scheduler\n"
        "celery-down:\n"
        "    docker compose stop celery-worker celery-beat\n"
        "[% endif %]",
        '[% if "docker" in addons %]'
        "# open flower monitoring UI on port 5555\n"
        "celery-flower:\n"
        "    docker compose run --rm celery-worker "
        "celery -A (( pkg_name )).tasks.celery_app flower --port=5555\n"
        "[% endif %]",
        '[% if "docker" in addons %]'
        "# tail celery worker logs\n"
        "celery-logs:\n"
        "    docker compose logs -f celery-worker\n"
        "[% endif %]",
    ],
)


def can_apply(project_dir: Path, lockfile: ZenitLockfile) -> str | None:
    pkg_name = normalise_pkg_name(project_dir.name)

    if not (project_dir / "src").is_dir():
        return (
            "No src/ directory found — celery addon expects a src layout.\n"
            "    Ensure your package lives under src/<pkg_name>/."
        )

    # Don't overwrite existing tasks directory contents.
    tasks_dir = project_dir / "src" / pkg_name / "tasks"
    if tasks_dir.is_dir() and any(tasks_dir.rglob("*.py")):
        return (
            f"{tasks_dir.relative_to(project_dir)}/ already contains Python files.\n"
            "    zenit won't overwrite existing task definitions.\n"
            "    Review that directory and remove any files if you want zenit to manage it:\n"
            f"      rm -r {tasks_dir.relative_to(project_dir)}"
        )

    # Check for any existing celery configuration anywhere in src/.
    src_dir = project_dir / "src"
    for py_file in src_dir.rglob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        if "from celery import" in text or "import celery" in text.lower():
            rel = py_file.relative_to(project_dir)
            return (
                f"{rel} already contains celery configuration.\n"
                "    zenit won't add celery alongside existing configuration.\n"
                "    Review that file and remove celery references if you want zenit to manage it."
            )

    return None


def health_check(project_dir: Path, lockfile: object) -> list[HealthIssue]:

    pkg_name = normalise_pkg_name(project_dir.name)
    issues: list[HealthIssue] = []

    celery_app = project_dir / "src" / pkg_name / "tasks" / "celery_app.py"
    if not celery_app.exists():
        return issues

    text = celery_app.read_text(encoding="utf-8")
    if "Celery(" in text:
        issues.append(
            HealthIssue(
                Severity.OK, "Celery app is configured in 'tasks/celery_app.py'."
            )
        )
    else:
        issues.append(
            HealthIssue(
                Severity.ERROR,
                "Celery app definition is missing from 'tasks/celery_app.py'.",
                hint="Restore the Celery(...) instantiation in tasks/celery_app.py.",
            )
        )

    return issues
