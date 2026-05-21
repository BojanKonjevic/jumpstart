from pathlib import Path

from zenit.cli.ui import info
from zenit.core.context import Context
from zenit.core.lockfile import ZenitLockfile
from zenit.core.pkg_name import normalise_pkg_name
from zenit.schema.models import (
    AddonConfig,
    EnvVar,
    FileContribution,
    Injection,
)

_HERE = Path(__file__).parent.absolute()

config = AddonConfig(
    id="auth-manual",
    description="JWT auth: register, login, refresh, logout, current user",
    requires=[],
    templates=["fastapi"],  # only valid for the fastapi template
    files=[
        FileContribution(
            dest="src/{{pkg_name}}/core/security.py",
            source=str(_HERE / "files" / "core" / "security.py"),
        ),
        FileContribution(
            dest="src/{{pkg_name}}/core/dependencies.py",
            source=str(_HERE / "files" / "core" / "dependencies.py.j2"),
            template=True,
        ),
        FileContribution(
            dest="src/{{pkg_name}}/models/user.py",
            source=str(_HERE / "files" / "models" / "user.py"),
        ),
        FileContribution(
            dest="src/{{pkg_name}}/models/refresh_token.py",
            source=str(_HERE / "files" / "models" / "refresh_token.py"),
        ),
        FileContribution(
            dest="src/{{pkg_name}}/schemas/auth.py",
            source=str(_HERE / "files" / "schemas" / "auth.py"),
        ),
        FileContribution(
            dest="src/{{pkg_name}}/api/routes/auth.py",
            source=str(_HERE / "files" / "api" / "routes" / "auth.py.j2"),
            template=True,
        ),
        FileContribution(
            dest="tests/integration/test_auth.py",
            source=str(_HERE / "files" / "tests" / "test_auth.py.j2"),
            template=True,
        ),
    ],
    env_vars=[
        EnvVar(
            key="SECRET_KEY",
            default="change-me-run-openssl-rand-hex-32",
            comment="generate with: openssl rand -hex 32",
        ),
        EnvVar(key="ACCESS_TOKEN_EXPIRE_MINUTES", default="30"),
        EnvVar(key="REFRESH_TOKEN_EXPIRE_DAYS", default="30"),
    ],
    deps=[
        "bcrypt",
        "python-jose[cryptography]",
    ],
    dev_deps=[],
    just_recipes=[
        '# generate a secret key for JWT signing\ngen-secret:\n    python -c "import secrets; print(secrets.token_hex(32))"',
    ],
    injections=[
        Injection(
            point="settings_fields",
            content=(
                '    secret_key: str = "change-me-in-production"\n'
                '    algorithm: str = "HS256"\n'
                "    access_token_expire_minutes: int = 30\n"
                "    refresh_token_expire_days: int = 30"
            ),
        ),
        Injection(
            point="router_imports",
            content="from .routes.auth import router as auth_router",
        ),
        Injection(
            point="router_includes",
            content='api_router.include_router(auth_router, prefix="/auth", tags=["auth"])',
        ),
        Injection(
            point="test_imports",
            content="from (( pkg_name )).models.user import User\nfrom (( pkg_name )).core.security import hash_password",
        ),
        Injection(
            point="test_fixtures",
            content='''
@pytest.fixture
async def test_user(session: AsyncSession) -> User:
    user = User(
        email="test@example.com",
        hashed_password=hash_password("testpassword123"),
        is_active=True,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


@pytest.fixture
async def auth_client(client: AsyncClient, test_user: User) -> AsyncClient:
    """Authenticated client — logged in as test_user."""
    resp = await client.post(
        "/auth/login",
        data={"username": test_user.email, "password": "testpassword123"},
    )
    token = resp.json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client''',
        ),
        Injection(
            point="exceptions",
            content=(
                "\n\nclass UnauthorizedError(HTTPException):\n"
                '    def __init__(self, detail: str = "Unauthorized") -> None:\n'
                "        super().__init__(\n"
                "            status_code=status.HTTP_401_UNAUTHORIZED,\n"
                "            detail=detail,\n"
                '            headers={"WWW-Authenticate": "Bearer"},\n'
                "        )\n\n\n"
                "class ForbiddenError(HTTPException):\n"
                '    def __init__(self, detail: str = "Forbidden") -> None:\n'
                "        super().__init__(status_code=status.HTTP_403_FORBIDDEN, detail=detail)"
            ),
        ),
    ],
)


def can_apply(project_dir: Path, lockfile: ZenitLockfile) -> str | None:
    if lockfile.template != "fastapi":
        return "auth-manual only works with the fastapi template."

    pkg_name = normalise_pkg_name(project_dir.name)

    security_file = project_dir / "src" / pkg_name / "core" / "security.py"
    if security_file.exists():
        return (
            f"{security_file.relative_to(project_dir)} already exists.\n"
            "    Remove it first if you want zenit to generate a fresh one:\n"
            f"      rm {security_file.relative_to(project_dir)}"
        )

    auth_route = project_dir / "src" / pkg_name / "api" / "routes" / "auth.py"
    if auth_route.exists():
        return (
            f"{auth_route.relative_to(project_dir)} already exists.\n"
            "    Remove it first:\n"
            f"      rm {auth_route.relative_to(project_dir)}"
        )

    for env_file in (".env", ".env.example"):
        path = project_dir / env_file
        if path.exists() and "SECRET_KEY" in path.read_text(encoding="utf-8"):
            return (
                f"SECRET_KEY is already defined in {env_file}.\n"
                "    Remove it first if you want zenit to manage it."
            )

    return None


def post_apply(ctx: Context) -> None:

    info("Run 'just migrate \"add users\"' then 'just upgrade' to create auth tables.")
    info("Run 'just gen-secret' to generate a SECRET_KEY and add it to .env.")
