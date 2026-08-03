# Addons

Addons are optional capabilities you layer on top of a Zenit template. Each addon is self-contained and declarative: it knows exactly what files it creates, what code it injects, what packages it requires. Addons can be applied at creation time or added later with `zenit add`. They can also be removed cleanly with `zenit remove`.

---

## Built-in addons

| Addon | Description | Requires |
|---|---|---|
| [`auth-manual`](./auth-manual.md) | JWT auth: register, login, refresh, logout | `fastapi` template only |
| [`celery`](./celery.md) | Celery worker + beat scheduler, backed by Redis | `redis` addon |
| [`docker`](./docker.md) | Dockerfile + compose.yml + .dockerignore | - |
| [`github-actions`](./github-actions.md) | CI workflow: lint, type-check, test on push/PR | - |
| [`postgres`](./postgres.md) | PostgreSQL driver + DATABASE_URL + compose service | - |
| [`redis`](./redis.md) | Async Redis connection helper with connection pooling | - |
| [`sentry`](./sentry.md) | Sentry error tracking + performance monitoring | - |
| [`sqlalchemy`](./sqlalchemy.md) | SQLAlchemy ORM + Alembic migrations | - |
| [`sqlmodel`](./sqlmodel.md) | SQLModel ORM (Pydantic + SQLAlchemy) | `sqlalchemy` addon, `fastapi` template |

---

## Compatibility matrix

| Addon | `blank` | `fastapi` | Addon deps |
|---|---|---|---|
| `docker` | ✓ | ✓ | - |
| `redis` | ✓ | ✓ | - |
| `celery` | ✓ | ✓ | `redis` |
| `auth-manual` | - | ✓ | `sqlalchemy` |
| `sentry` | ✓ | ✓ | - |
| `github-actions` | ✓ | ✓ | - |
| `sqlalchemy` | ✓ | ✓ | - |
| `postgres` | ✓ | ✓ | - |
| `sqlmodel` | - | ✓ | `sqlalchemy` |

When an addon requires another (e.g. `celery` → `redis`), `zenit add celery` resolves the dependency automatically and installs both.

---

## How addons work

Each addon is a directory under `src/zenit/addons/` containing:

- `addon.py` - the manifest that declares everything the addon does
- `files/` - optional Jinja2 templates and static files to copy

The manifest declares:

- **Files** to create (rendered from Jinja2 or copied verbatim)
- **Injections** - code blocks inserted into existing template files
- **Dependencies** - packages added to `pyproject.toml`
- **Compose services** - Docker services merged into `compose.yml`
- **Environment variables** - keys appended to `.env` and `.env.example`
- **Just recipes** - task runner recipes appended to the `justfile`

See [Architecture: Addons & Templates](../architecture/addons-and-templates.md) for the full technical reference on writing new addons, including a step-by-step tutorial.

---

## Adding an addon

```bash
zenit add redis
```

This runs the full addon pipeline: write files, inject code, update dependencies, merge compose services, append env vars, add recipes, and record everything in `.zenit.toml`.

See [`zenit add`](../commands/add.md) for full documentation.

---

## Removing an addon

```bash
zenit remove redis
```

This reverses every change the addon made: delete files, excise injected code, remove dependencies, remove compose services, delete env vars, remove recipes, and clean up `.zenit.toml`.

See [`zenit remove`](../commands/remove.md) for full documentation.
