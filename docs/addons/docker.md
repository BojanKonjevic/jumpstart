# docker

> Optional for all templates.

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

- Uses `python:3.12-slim` as the base image
- Installs `uv` from the official Astral container image
- Creates a non-root `app` user for security
- Copies `pyproject.toml` and `uv.lock` first for layer caching
- Installs dependencies with `uv sync --frozen --no-dev --no-install-project`
- Copies source code and installs the project
- Exposes port 8000
- Sets `PYTHONPATH=/app/src`

For `fastapi` projects, the default CMD runs uvicorn. For `blank` projects, it runs `python -m <pkg_name>`.

### Compose services

The docker addon adds a single `app` service:

| Service | Image | Purpose |
|---|---|---|
| `app` | Build from Dockerfile | The application with hot-reload |

The `app` service mounts `.env` for configuration, uses Docker Compose watch mode to sync `./src`, and runs the appropriate command (`uvicorn` for FastAPI, `python -m` for blank).

Additional services (e.g. `db` for PostgreSQL) come from other addons - the `postgres` addon adds its own service automatically.

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

> docker can be removed from any project, regardless of template.
