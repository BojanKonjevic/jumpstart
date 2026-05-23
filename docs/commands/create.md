# zenit create

Scaffold a new Python project from a template, with optional addons applied at creation time.

```
zenit create <name>
```

---

## What it does

In order:

1. Creates a new directory with the given name in the current working directory.
2. Prompts for a template and addons (if not already provided via config defaults).
3. Renders and writes all template files, applying the Jinja2 context.
4. Applies each selected addon in order — files, injections, dependencies, compose services, env vars, recipes.
5. Writes `pyproject.toml` and `justfile`.
6. Runs `git init` and makes an initial commit.
7. Writes `.zenit.toml`.

If any step fails, all written files are removed and the directory is left in the state it was in before the command ran. The initial commit is not made if a later step fails.

---

## Arguments

| Argument | Description |
|---|---|
| `name` | The project directory name. Also used as the default value for the project name prompt. Required. |

---

## Options

| Flag | Description |
|---|---|---|
| `--template` / `-t` | Template to use. Skips the template picker. |
| `--addons` / `-a` | Addon(s) to include. Repeat the flag or use comma-separated values (e.g. `-a redis,celery`). Skips the addon picker. |
| `--dry-run` | Print all files that would be created and all changes that would be made, without writing anything. |
| `--version` | Show the Zenit version and exit. |

---

## Interactive prompts

When run without `--template` or `--addons`, Zenit asks three questions in order. Arrow keys navigate each prompt; Enter confirms. In environments without a TTY (CI, pipes), Zenit falls back to numbered input automatically.

**1. Template**

```
Template:
  ❯ fastapi
    blank
```

Select the project template. See [Templates](../templates/index.md) for what each one generates. Pass `--template` to skip this prompt.

**2. Addons**

```
Addons (space to select, enter to confirm):
  ❯ ◉ docker
    ◯ redis
    ◯ celery
    ◯ auth-manual
    ◯ sentry
    ◯ github-actions
    ◯ sqlalchemy
    ◯ postgres
    ◯ sqlmodel
```

Space toggles selection. The list shows only addons compatible with the selected template. If an addon has unmet dependencies (e.g. `celery` requires `redis`), selecting it automatically selects its dependencies. Pass `--addons` to skip this prompt.

**3. Project name**

```
Project name [my-api]:
```

The human-readable project name, used in `pyproject.toml` as `[project].name`. Defaults to the directory name passed as the `create` argument.

The Python package name is derived automatically from the project name (hyphens replaced by underscores). No separate package-name prompt is shown.

---

## Config defaults

If you have a config file, the addon and template prompts open with your defaults pre-selected. You can still change them before confirming.

```toml
# ~/.config/zenit/zenit.toml  (Linux / macOS)
# %APPDATA%\zenit\zenit.toml  (Windows)
default_template = "fastapi"
default_addons = ["docker", "github-actions"]
```

---

## Generated output: `blank` template

```
my-project/
├── .zenit.toml
├── pyproject.toml
├── justfile
├── .envrc
├── .gitignore
├── .gitattributes
├── .pre-commit-config.yaml
├── shell.nix
├── my_project/
│   ├── __main__.py
│   └── main.py
└── tests/
    └── test_main.py
```

The `blank` template produces a minimal Python package: a `main.py` entry point, a `__main__.py` so the package is runnable with `python -m my_project`, and a single passing test. Everything else is standard tooling config.

---

## Generated output: `fastapi` template

```
my-project/
├── .zenit.toml
├── pyproject.toml
├── justfile
├── .env
├── .env.example
├── .envrc
├── .gitignore
├── .gitattributes
├── .pre-commit-config.yaml
├── shell.nix
└── my_project/
    ├── main.py              # FastAPI app instance, lifespan, middleware
    ├── settings.py          # Pydantic Settings wired to .env
    ├── lifecycle.py         # Lifespan startup/shutdown hooks
    ├── exceptions.py        # Global exception handlers
    ├── api/
    │   ├── router.py        # Registers all route groups
    │   └── routes/
    │       └── health.py    # GET /health
    ├── schemas/
    │   └── common.py        # PaginationParams, PaginatedResponse[T]
    └── tests/
        └── test_health.py

If you also select the `sqlalchemy` and `postgres` addons, the generated project gains the database layer (db/, alembic/, models/mixins.py, scripts/wait_db.py, tests/conftest.py).

---

## The generated `justfile`

Every project gets a `justfile` regardless of template. It provides a consistent set of task runner recipes:

| Recipe | What it runs |
|---|---|
| `just run` | Start the app (with Docker services if present) and launch with hot-reload |
| `just test` | `uv run pytest` |
| `just lint` | `uv run ruff check` |
| `just fmt` | `uv run ruff format` |
| `just check` | `uv run mypy` (strict) |
| `just build` | `uv build` |

Addons may append additional recipes. The `docker` addon adds `just up` and `just down` for managing containers independently of the app process.

---

## Error conditions

| Situation | Behaviour |
|---|---|
| Directory `<name>` already exists | Exits immediately with an error. Nothing is written. |
| Invalid project name (empty, contains `/`, starts with `.`) | Exits with a validation error before any prompts. |
| Unknown template selected | Cannot occur via interactive prompt; exits with an error if somehow triggered. |
| Unknown addon selected | Same as above. |
| `uv` not found on PATH | Exits with an error and a link to the uv install instructions. |
| `git` not found on PATH | Exits with an error. Git is required for the initial commit and for project versioning. |
| Addon dependency conflict | Exits with an error identifying the conflicting requirements before any files are written. |

---

## Examples

Scaffold interactively:

```bash
zenit create my-api
```

Scaffold with config defaults pre-selected (still interactive — confirm or change before proceeding):

```bash
# with default_template = "fastapi" and default_addons = ["docker"] in config
zenit create my-api
```

Preview what would be generated without writing anything:

```bash
zenit create my-api --dry-run
```
