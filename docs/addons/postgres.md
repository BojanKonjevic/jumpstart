# postgres

PostgreSQL driver, `DATABASE_URL` configuration, database management recipes, and a Docker Compose service.

---

## When to use it

Choose `postgres` when your project needs:

- Async PostgreSQL access via `asyncpg`
- A `DATABASE_URL` environment variable for connection configuration
- A PostgreSQL container in Docker Compose (requires `docker` addon)
- Database creation and reset scripts

---

## What it adds

### Files

| File | Purpose |
|---|---|
| `my_project/scripts/wait_db.py` | Polls PostgreSQL until ready (used by justfile) |

### Code injections

| Point | Target | What it adds |
|---|---|---|
| `settings_fields` | `settings.py` | `database_url: str = "postgresql+asyncpg://..."` |

### Environment variables

| Key | Default |
|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/my_project` |

### Compose services

When the `docker` addon is also installed, the following service is added to `compose.yml`:

| Service | Image | Purpose |
|---|---|---|
| `db` | `postgres:16` | PostgreSQL with persistent volume (`./.pgdata`) |

### Dependencies

| Package | Purpose |
|---|---|
| `asyncpg` | Async PostgreSQL driver |

### Justfile recipes

| Recipe | Command |
|---|---|
| `just wait-db` | `uv run python scripts/wait_db.py` |
| `just db-create` | Start postgres, create dev/test databases, run migrations |
| `just db-reset` | Drop and recreate both databases |

> [!NOTE]
> The `db-create` and `db-reset` recipes only start the PostgreSQL container when the `docker` addon is installed.

---

## Usage

With the `docker` addon:

```bash
cd my-project
just db-create
```

Without Docker, set `DATABASE_URL` in `.env` to point at your own PostgreSQL instance.
