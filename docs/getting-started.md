# Getting Started

Get a project running in under five minutes.

---

## Requirements

- **Python 3.14+**
- **uv 0.4+** — [install](https://docs.astral.sh/uv/getting-started/installation/)
- **git**
- **just** — optional, but generated projects use it heavily
- **direnv** — optional, auto-activates the virtualenv on `cd`

Docker is optional — add the `docker` addon if you want containers.

> [!NOTE]
> **NixOS:** set `UV_PYTHON_DOWNLOADS=never` before installing. Generated projects detect NixOS automatically and write a `shell.nix` + `.envrc` that activates the system Python via direnv.

---

## Install Zenit

Zenit is a dev-time tool. It is never a runtime dependency of the projects it generates. Once a project is created, it works without Zenit.

```bash
uv tool install zenit
```

To run without installing:

```bash
uvx zenit my-project
```

Verify:

```bash
zenit --version
```

---

## Create a project

```bash
zenit create my-api
```

Zenit will ask a few questions:

```
Template:
  ❯ fastapi
    blank

Addons (space to select, enter to confirm):
  ❯ ◯ docker
    ◯ redis
    ◯ celery
    ◯ auth-manual
    ◯ sentry
    ◯ github-actions
    ◯ sqlalchemy
    ◯ postgres
    ◯ sqlmodel

Project name [my-api]:
```

Select **fastapi** as the template, then **docker**, **sqlalchemy**, and **postgres** as addons. Arrow keys navigate; space toggles; enter confirms. The package name is derived automatically from the project name. In CI environments without a TTY, Zenit falls back to numbered input automatically.

> [!TIP]
> Set personal defaults in your config file so they appear pre-selected every time:
> ```toml
> # ~/.config/zenit/zenit.toml  (Linux / macOS)
> # %APPDATA%\zenit\zenit.toml  (Windows)
> default_template = "fastapi"
> default_addons = ["docker", "github-actions"]
> ```

---

## What was generated

```
my-api/
├── .zenit.toml              # Zenit's manifest — tracks what was generated
├── pyproject.toml
├── justfile                 # task runner recipes (run, test, lint, …)
├── .env                     # local env vars (not committed)
├── .env.example             # committed template for .env
├── compose.yml              # Docker Compose — app + postgres
├── Dockerfile
├── alembic.ini              # from sqlalchemy addon
├── alembic/                 # from sqlalchemy addon
│   └── env.py
├── my_api/
│   ├── main.py              # FastAPI app, lifespan, middleware
│   ├── settings.py          # Pydantic Settings — reads from .env
│   ├── lifecycle.py         # startup/shutdown hooks
│   ├── exceptions.py        # global exception handlers
│   ├── api/
│   │   ├── router.py
│   │   └── routes/
│   │       └── health.py    # GET /health — always present
│   ├── db/                  # from sqlalchemy addon
│   │   ├── base.py
│   │   └── session.py
│   ├── models/
│   │   └── mixins.py        # TimestampMixin — from sqlalchemy addon
│   ├── schemas/
│   │   └── common.py        # PaginationParams, PaginatedResponse[T]
│   └── scripts/
│       └── wait_db.py       # from postgres addon
└── tests/
    ├── conftest.py
    └── test_health.py
```

`.zenit.toml` is the only file that links this project to Zenit. The rest is plain Python — no Zenit-specific imports, no runtime dependency.

> [!NOTE]
> Zenit's core pipeline is validated by 986+ tests covering injection, removal, round-trip integrity, and edge cases. What you see in `.zenit.toml` matches what actually happened.

---

## Run it

```bash
cd my-api
just run
```

This starts the Docker containers (Postgres from the `postgres` addon) and launches the API server with hot-reload. Open `http://localhost:8000/health` to confirm it's running.

Other useful recipes:

```bash
just test      # run pytest
just lint      # ruff check
just fmt       # ruff format
just check     # mypy strict
```

---

## Add an addon later

```bash
zenit add sentry
```

Zenit installs the addon, injects the wiring, updates `pyproject.toml`, and records everything in `.zenit.toml`. Nothing is left in an inconsistent state — if anything fails, the entire operation rolls back.

---

## Escape hatch

Zenit never traps you. To stop using it on a project:

```bash
rm .zenit.toml   # Zenit can no longer manage the project
uv tool uninstall zenit   # remove Zenit itself
```

The project continues to work exactly as before.

---

## Next steps

- [Architecture Overview](./architecture/index.md) — understand how Zenit works and why it was designed this way
- [Building an addon](./architecture/addons-and-templates.md) — write your own addon
- [Commands Reference](./commands/index.md) — every flag and option for all five commands
