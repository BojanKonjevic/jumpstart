# docker

> **Required by:** `fastapi` template (auto-selected and locked). Optional for `blank`.

The `docker` addon adds containerisation support to any Zenit project. It generates a multi-stage Dockerfile, a Docker Compose configuration, and a `.dockerignore` file.

---

## When to use it

Choose `docker` when you want to:

- Containerise your application for consistent deployments
- Run the app locally with Docker Compose alongside dependencies (PostgreSQL, Redis)
- Build optimised production images with multi-stage builds
- Use Docker Compose watch mode for live code syncing during development

---

## What it adds

### Files

| File | Purpose |
|---|---|
| `Dockerfile` | Multi-stage build using `uv` for dependency management |
| `compose.yml` | Docker Compose services: app, PostgreSQL (fastapi only) |
| `.dockerignore` | Excludes build artefacts, caches, and local env files |

### Dockerfile

The generated Dockerfile:

- Uses `python:3.14-slim` as the base image
- Installs `uv` from the official Astral container image
- Creates a non-root `app` user for security
- Copies `pyproject.toml` and `uv.lock` first for layer caching
- Installs dependencies with `uv sync --frozen --no-dev --no-install-project`
- Copies source code and installs the project
- Exposes port 8000
- Sets `PYTHONPATH=/app/src`

For `fastapi` projects, the default CMD runs uvicorn. For `blank` projects, it runs `python -m <pkg_name>`.

### Compose services

**FastAPI projects** get two services:

| Service | Image | Purpose |
|---|---|---|
| `app` | Build from Dockerfile | The FastAPI application with hot-reload |
| `db` | `postgres:16` | PostgreSQL database with persistent volume |

The `app` service mounts `.env` for configuration, uses Docker Compose watch mode to sync `./src`, and runs uvicorn with `--reload`.

The `db` service persists data in `./.pgdata` (gitignored) and exposes port 5432.

**Blank projects** get only the `app` service.

### Just recipes

| Recipe | Command |
|---|---|
| `just docker-up` | Build and start all services |
| `just docker-down` | Stop all services |

---

## Usage

### Development

```bash
just docker-up    # Build and start app + db
just docker-down  # Stop everything
```

Code changes in `src/` are reflected immediately via watch mode.

### Production builds

```bash
docker build -t my-project .
docker run -p 8000:8000 --env-file .env my-project
```

The production image has no dev dependencies and runs as the non-root `app` user.

---

## Removing the addon

`zenit remove docker` will delete `Dockerfile`, `compose.yml`, and `.dockerignore`, and remove the docker recipes from the justfile.

> [!NOTE]
> For `fastapi` projects, `docker` is required by the template and cannot be removed.
