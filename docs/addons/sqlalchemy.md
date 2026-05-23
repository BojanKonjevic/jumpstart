# sqlalchemy

SQLAlchemy ORM with async support and Alembic migrations.

---

## When to use it

Choose `sqlalchemy` when your project needs:

- An ORM with async PostgreSQL support via SQLAlchemy
- Database migrations managed by Alembic
- A `DeclarativeBase` for your models
- An async session factory and `get_session` FastAPI dependency

---

## What it adds

### Files

| File | Purpose |
|---|---|
| `my_project/db/__init__.py` | Package marker |
| `my_project/db/base.py` | SQLAlchemy `DeclarativeBase` |
| `my_project/db/session.py` | `create_async_engine`, `async_sessionmaker`, `get_session` dependency |
| `my_project/models/__init__.py` | Imports all models for Alembic discovery |
| `my_project/models/mixins.py` | `TimestampMixin` with `created_at` and `updated_at` |
| `alembic.ini` | Alembic configuration |
| `alembic/env.py` | Alembic environment wired to async SQLAlchemy |
| `alembic/script.py.mako` | Migration script template |

### Code injections

| Point | Target | What it adds |
|---|---|---|
| `lifespan_imports` | `lifecycle.py` | `from .db.session import engine` |
| `lifespan_shutdown` | `lifecycle.py` | `await engine.dispose()` |

### Dependencies

| Package | Purpose |
|---|---|
| `sqlalchemy[asyncio]` | ORM with async support |
| `alembic` | Database migrations |

Dev dependencies: `aiosqlite` (for testing with SQLite).

### Justfile recipes

| Recipe | Command |
|---|---|
| `just migrate msg=""` | `uv run alembic revision --autogenerate -m "msg"` |
| `just upgrade` | `uv run alembic upgrade head` |
| `just downgrade` | `uv run alembic downgrade -1` |

---

## Compatibility

Works with both `blank` and `fastapi` templates. When used with `fastapi`, the `get_session` dependency is wired for use with route handlers.

> [!NOTE]
> The `sqlalchemy` addon provides the ORM layer but does not include a database driver or compose service. Add the `postgres` addon for asyncpg and a PostgreSQL container, or configure your own database URL in `.env`.
