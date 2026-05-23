from pathlib import Path

from zenit.addons._preflight import (
    reject_existing_file,
    reject_existing_in_env,
    require_src_layout,
)
from zenit.core.lockfile import ZenitLockfile
from zenit.core.pkg_name import normalise_pkg_name
from zenit.doctor.doctor import HealthIssue, Severity
from zenit.schema.models import AddonConfig, EnvVar, FileContribution, Injection

_HERE = Path(__file__).parent.absolute()

config = AddonConfig(
    id="sentry",
    description="Sentry error tracking + performance monitoring",
    requires=[],
    files=[
        FileContribution(
            dest="src/{{pkg_name}}/integrations/__init__.py",
            content="",
        ),
        FileContribution(
            dest="src/{{pkg_name}}/integrations/sentry.py",
            source=str(_HERE / "files" / "sentry.py.j2"),
            template=True,
        ),
    ],
    env_vars=[
        EnvVar(key="SENTRY_DSN", default=""),
        EnvVar(key="SENTRY_ENVIRONMENT", default="development"),
    ],
    deps=["sentry-sdk[fastapi]", "python-dotenv"],
    just_recipes=[
        "# print sentry-sdk version\nsentry-check:\n    uv run python -c \"import sentry_sdk; print('sentry-sdk', sentry_sdk.VERSION)\"",
        "# check whether SENTRY_DSN is set\nsentry-test:\n    uv run python -c \"from (( pkg_name )).integrations.sentry import init_sentry; import os; init_sentry(); print('Sentry DSN:', os.environ.get('SENTRY_DSN') or 'not set')\"",
    ],
    injections=[
        Injection(
            point="lifespan_startup",
            templates=["fastapi"],
            content="    from .integrations.sentry import init_sentry\n    init_sentry()",
        ),
        Injection(
            point="main_startup",
            templates=["blank"],
            content="    from .integrations.sentry import init_sentry\n    init_sentry()",
        ),
        Injection(
            point="settings_fields",
            templates=["fastapi"],
            content='    sentry_dsn: str = ""\n    sentry_environment: str = "development"',
        ),
    ],
)


def can_apply(project_dir: Path, lockfile: ZenitLockfile) -> str | None:
    pkg_name = normalise_pkg_name(project_dir.name)
    template = lockfile.template

    reason = require_src_layout(project_dir, "sentry")
    if reason:
        return reason

    sentry_file = project_dir / "src" / pkg_name / "integrations" / "sentry.py"
    reason = reject_existing_file(sentry_file, project_dir)
    if reason:
        return reason

    if template == "fastapi":
        target = project_dir / "src" / pkg_name / "lifecycle.py"
        if not target.exists():
            return (
                "lifecycle.py not found — has it been moved or deleted?\n"
                "    zenit needs to inject init_sentry() into the lifespan function.\n"
                "    Restore lifecycle.py or add the call manually."
            )
        if "sentry_sdk" in target.read_text(encoding="utf-8"):
            return (
                "lifecycle.py already references sentry_sdk.\n"
                "    zenit won't add a second initialisation.\n"
                "    Remove the existing sentry_sdk references from lifecycle.py first."
            )
    else:
        target = project_dir / "src" / pkg_name / "main.py"
        if not target.exists():
            return (
                "main.py not found — has it been moved or deleted?\n"
                "    zenit needs to inject init_sentry() into the main() function.\n"
                "    Restore main.py or add the call manually."
            )
        if "sentry_sdk" in target.read_text(encoding="utf-8"):
            return (
                "main.py already references sentry_sdk.\n"
                "    zenit won't add a second initialisation.\n"
                "    Remove the existing sentry_sdk references from main.py first."
            )

    return reject_existing_in_env(project_dir, "SENTRY_DSN")


def health_check(project_dir: Path, lockfile: ZenitLockfile) -> list[HealthIssue]:

    pkg_name = normalise_pkg_name(project_dir.name)
    issues: list[HealthIssue] = []

    sentry_file = project_dir / "src" / pkg_name / "integrations" / "sentry.py"
    if not sentry_file.exists():
        return issues

    template = lockfile.template

    if template == "fastapi":
        target = project_dir / "src" / pkg_name / "lifecycle.py"
        label = "lifecycle.py"
    else:
        target = project_dir / "src" / pkg_name / "main.py"
        label = "main.py"

    if not target.exists():
        return issues

    text = target.read_text(encoding="utf-8")
    if "init_sentry()" in text:
        issues.append(HealthIssue(Severity.OK, f"Sentry is initialised in '{label}'."))
    else:
        issues.append(
            HealthIssue(
                Severity.ERROR,
                f"Sentry is installed but 'init_sentry()' is not called in '{label}'.",
                hint=f"Add 'from .integrations.sentry import init_sentry; init_sentry()' "
                f"to the startup block in '{label}'.",
            )
        )

    return issues
