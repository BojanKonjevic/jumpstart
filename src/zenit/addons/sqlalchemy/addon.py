from pathlib import Path

from zenit.schema.models import (
    AddonConfig,
    EnvVar,
    FileContribution,
    Injection,
)

_HERE = Path(__file__).parent.absolute()

config = AddonConfig(
    id="sqlalchemy",
    description="SQLAlchemy ORM + Alembic migrations",
    requires=[],
    dirs=[
        "src/{{pkg_name}}/db",
        "alembic/versions",
    ],
    files=[
        FileContribution(
            dest="src/{{pkg_name}}/db/__init__.py",
            content="",
        ),
        FileContribution(
            dest="src/{{pkg_name}}/db/base.py",
            source=str(_HERE / "files" / "src" / "{{pkg_name}}" / "db" / "base.py"),
        ),
        FileContribution(
            dest="src/{{pkg_name}}/db/session.py",
            source=str(
                _HERE / "files" / "src" / "{{pkg_name}}" / "db" / "session.py.j2"
            ),
            template=True,
        ),
        FileContribution(
            dest="src/{{pkg_name}}/models/mixins.py",
            source=str(
                _HERE / "files" / "src" / "{{pkg_name}}" / "models" / "mixins.py"
            ),
        ),
        FileContribution(
            dest="alembic.ini",
            source=str(_HERE / "files" / "alembic.ini.j2"),
            template=True,
        ),
        FileContribution(
            dest="alembic/env.py",
            source=str(_HERE / "files" / "alembic" / "env.py.j2"),
            template=True,
        ),
        FileContribution(
            dest="alembic/script.py.mako",
            source=str(_HERE / "files" / "alembic" / "script.py.mako"),
        ),
    ],
    deps=[
        "sqlalchemy[asyncio]",
        "alembic",
    ],
    dev_deps=[
        "aiosqlite",
    ],
    env_vars=[
        EnvVar(key="DATABASE_URL", default="sqlite+aiosqlite:///./dev.db"),
    ],
    just_recipes=[
        '# generate a new alembic migration\nmigrate msg="":\n    uv run alembic revision --autogenerate -m "{{msg}}"',
        "# apply all pending migrations\nupgrade:\n    uv run alembic upgrade head",
        "# roll back one migration\ndowngrade:\n    uv run alembic downgrade -1",
    ],
    injections=[
        Injection(
            point="settings_fields",
            templates=["fastapi"],
            content='[% if "postgres" not in addons %]\n    database_url: str = "sqlite+aiosqlite:///./dev.db"\n[% endif %]',
        ),
        Injection(
            point="lifespan_imports",
            content="\nfrom .db.session import engine",
        ),
        Injection(
            point="lifespan_shutdown",
            content="    await engine.dispose()",
        ),
    ],
)
