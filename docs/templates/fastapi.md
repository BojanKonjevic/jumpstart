# fastapi

The `fastapi` template produces a production-oriented async FastAPI application. It is the default template for web API projects. Database access (SQLAlchemy, Alembic, asyncpg) and Docker support come from addons — select `sqlalchemy`, `postgres`, and `docker` at creation time to include them.

---

## When to use it

Choose `fastapi` when you are building a web API, microservice, or any project that needs:

- An async HTTP framework with automatic OpenAPI documentation
- Pydantic settings management with `.env` file support
- Optional database access via SQLAlchemy (add `sqlalchemy` addon)
- Optional PostgreSQL (add `postgres` addon)
- Optional Docker Compose (add `docker` addon)

> [!NOTE]
> The `fastapi` template does not require any addon by default. Add the ones you need — `sqlalchemy`, `postgres`, and `docker` are the most common choices.

---

## What gets generated

```
my-project/
├── .zenit.toml              # Zenit's manifest — tracks what was generated
├── pyproject.toml           # Project metadata and dependencies
├── justfile                 # Task runner recipes
├── .env                     # Local environment variables (not committed)
├── .env.example             # Committed template for .env
├── .envrc                   # direnv hook (optional)
├── .gitignore
├── .gitattributes
├── .pre-commit-config.yaml  # Ruff lint, ruff format, mypy on every commit
├── shell.nix                # NixOS only
└── my_project/
    ├── __init__.py          # Package version string
    ├── main.py              # FastAPI app instance, lifespan, middleware
    ├── settings.py          # Pydantic Settings wired to .env
    ├── lifecycle.py         # Lifespan startup/shutdown hooks
    ├── exceptions.py        # Global exception handlers
    ├── api/
    │   ├── __init__.py
    │   ├── router.py        # Registers all route groups
    │   └── routes/
    │       ├── __init__.py
    │       └── health.py    # GET /health — always generated
    ├── core/
    │   └── __init__.py
    ├── schemas/
    │   ├── __init__.py
    │   └── common.py        # PaginationParams, PaginatedResponse[T]
    └── tests/
        ├── conftest.py      # pytest fixtures: async session, HTTP client
        ├── integration/
        │   └── test_health.py   # Smoke test for GET /health
        ├── unit/
        └── fixtures/
```

---

## Architecture

### Application entry point

`main.py` creates the FastAPI app with lifespan management:

```python
from fastapi import FastAPI
from .api.router import api_router
from .lifecycle import lifespan

app = FastAPI(title="my-project", version="0.1.0", lifespan=lifespan)
app.include_router(api_router)
```

### Lifespan

`lifecycle.py` provides an async context manager for startup/shutdown:

```python
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    yield
    await engine.dispose()
```

Addons inject into `lifespan_startup` (before `yield`) and `lifespan_shutdown` (after `yield`).

### Settings

`settings.py` uses Pydantic Settings with `.env` file support:

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/my_project"
    debug: bool = False
```

Addons inject into `settings_fields` to add their own configuration fields.

### Router registration

`api/router.py` is the central router. Addons inject into `router_imports` and `router_includes` to register their routers with prefixes.

### Testing

`tests/conftest.py` provides:

- `session` — creates a test database, runs `Base.metadata.create_all`, yields an async session, then drops everything
- `client` — overrides `get_session` with the test session and yields an `httpx.AsyncClient`

Addons inject into `test_imports` and `test_fixtures` to add addon-specific fixtures.

---

## Injection points

| Point | File | Locator | What goes here |
|---|---|---|---|---|
| `settings_fields` | `src/{{pkg_name}}/settings.py` | `after_last_class_attribute` (`Settings`) | Configuration fields |
| `lifespan_imports` | `src/{{pkg_name}}/lifecycle.py` | `after_last_import` | Import statements needed by lifespan hooks |
| `lifespan_startup` | `src/{{pkg_name}}/lifecycle.py` | `before_yield_in_function` (`lifespan`) | Startup logic |
| `lifespan_shutdown` | `src/{{pkg_name}}/lifecycle.py` | `in_function_body` (after `yield`) | Cleanup logic |
| `router_imports` | `src/{{pkg_name}}/api/router.py` | `after_last_import` | Import statements for addon routers |
| `router_includes` | `src/{{pkg_name}}/api/router.py` | `after_statement_matching` (`router.include_router`) | `api_router.include_router(...)` calls |
| `test_imports` | `tests/conftest.py` | `after_last_import` | Test fixture imports |
| `test_fixtures` | `tests/conftest.py` | `at_module_end` | Additional pytest fixtures |
| `exceptions` | `src/{{pkg_name}}/exceptions.py` | `at_module_end` | Custom exception classes |
| `env_vars` | `.env` | `at_file_end` | Environment variable definitions |

---

## Dependencies

| Package | Purpose |
|---|---|
| `fastapi` | Web framework |
| `uvicorn[standard]` | ASGI server |
| `pydantic-settings` | Settings management from environment |
| `email-validator` | Email validation for Pydantic |
| `python-multipart` | Form data parsing |
| `python-dotenv` | `.env` file loading |

The `sqlalchemy`, `postgres`, and `sqlmodel` addons add additional dependencies (`sqlalchemy[asyncio]`, `alembic`, `asyncpg`, `sqlmodel`, etc.) when selected.

---

## Justfile recipes

| Recipe | Command |
|---|---|---|
| `just run` | `uv run uvicorn my_project.main:app --reload` |
| `just test` | `uv run pytest -v` |
| `just cov` | `uv run pytest --cov=src --cov-report=term-missing` |
| `just lint` | `uv run ruff check .` |
| `just fmt` | `uv run ruff format .` |
| `just fix` | `ruff check --fix` + `ruff format` |
| `just check` | `uv run mypy src/` |

The `sqlalchemy` addon adds migration recipes (`just migrate`, `just upgrade`, `just downgrade`). The `postgres` addon adds database recipes (`just wait-db`, `just db-create`, `just db-reset`). See the respective addon docs for details.

---

## Database setup (with addons)

If you selected the `sqlalchemy` and `postgres` addons, a complete database layer is added to the project. After scaffolding, create the databases and run migrations:

```bash
cd my-project
just db-create
```

This starts the PostgreSQL container, creates the development and test databases, and applies all pending migrations.

Without these addons, the `fastapi` template has no database layer — add them later with `zenit add sqlalchemy postgres`.
