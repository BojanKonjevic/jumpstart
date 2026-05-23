# zenit list

List available templates and addons, or what is currently installed in the project.

```
zenit list <--available | --installed>
```

---

## Options

| Flag | Description |
|---|---|
| `--available` | List all templates and addons Zenit knows about, with descriptions. Does not require a Zenit project. |
| `--installed` | List what is installed in the current project. Requires `.zenit.toml`. |

With no flag: if run inside a Zenit project, shows installed addons followed by addons available to add. If run outside a Zenit project, behaves as `--available`.

---

## `zenit list --available`

Lists every template and addon built into this version of Zenit:

```
$ zenit list --available

Templates
  blank       Minimal Python package with pytest, ruff, mypy, and a justfile.
  fastapi     Production-oriented FastAPI with SQLAlchemy, Alembic, and asyncpg.

Addons
  auth-manual   JWT auth: register, login, refresh, logout. Requires fastapi template.
  celery        Celery worker and beat scheduler, backed by Redis. Requires redis.
  docker        Dockerfile, compose.yml, and .dockerignore.
  github-actions  CI workflow: lint, type-check, test on push and PR.
  postgres      PostgreSQL driver + DATABASE_URL + compose service.
  redis         Async Redis connection helper with connection pooling.
  sentry        Sentry SDK initialisation. No-ops when DSN is unset.
  sqlalchemy    SQLAlchemy ORM + Alembic migrations.
  sqlmodel      SQLModel ORM (Pydantic + SQLAlchemy). Requires sqlalchemy, fastapi template.
```

---

## `zenit list --installed`

Lists what is installed in the current project, including the template and the Zenit version that last wrote the manifest:

```
$ zenit list --installed

Project   my-api
Template  fastapi  
Version   zenit 1.0.8

Installed addons
  docker
  redis
```

Must be run from a directory containing `.zenit.toml`, or a subdirectory of one.

---

## Default (no flag)

When run inside a Zenit project with no flag, shows both installed addons and what is still available to add:

```
$ zenit list

Project   my-api
Template  fastapi
Version   zenit 1.0.8

Installed
  docker
  redis

Available to add
  auth-manual   JWT auth: register, login, refresh, logout.
  celery        Celery worker and beat scheduler. Requires redis (already installed).
  github-actions  CI workflow: lint, type-check, test on push and PR.
  sentry        Sentry SDK initialisation.
```

Addons already installed are not repeated in "Available to add". Addons incompatible with the current template are not shown.

---

## Error conditions

| Situation | Behaviour |
|---|---|
| `--installed` used outside a Zenit project | Exits with an error. |
| `.zenit.toml` exists but is malformed | Exits with an error describing the parse failure. |
