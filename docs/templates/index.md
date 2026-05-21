# Templates

Templates are the foundation of every Zenit project. When you run `zenit create`, you pick one template. It determines the overall structure — whether you get a FastAPI app with SQLAlchemy and Alembic, or a minimal blank package. The template also declares the injection points that addons are allowed to target.

---

## Built-in templates

| Template | Description | Use for |
|---|---|---|
| [`blank`](./blank.md) | Minimal Python package with pytest, ruff, mypy, and a justfile | CLI tools, scripts, libraries |
| [`fastapi`](./fastapi.md) | FastAPI + SQLAlchemy + Alembic + asyncpg | Web APIs, microservices |

---

## How templates work

Each template is a directory under `src/zenit/templates/` containing:

- `template.py` — the manifest that declares everything the template provides
- `files/` — Jinja2 templates and static files rendered into the project

The manifest declares:

- **Files** to create — rendered from Jinja2 using the project context (name, package name, addons)
- **Directories** to create
- **Injection points** — named locations in generated files where addons can insert code
- **Dependencies** — packages added to `pyproject.toml`
- **Dev dependencies** — test and lint tooling
- **Compose services** — Docker services for local development
- **Environment variables** — keys written to `.env` and `.env.example`
- **Just recipes** — task runner recipes for the justfile

Templates use `(( ))` for variable substitution and `[% %]` for control flow to avoid conflicts with literal `{{ }}` and `{% %}` in Docker Compose, GitHub Actions, and Alembic files.

**Important:** Templates are not upgradeable in place. If you start with `blank` and later need FastAPI, re-scaffold with the `fastapi` template and migrate your code.

---

## Common files

Every project, regardless of template, receives these files from `templates/_common/`:

| File | Purpose |
|---|---|
| `.gitignore` | Standard Python gitignore |
| `.gitattributes` | LF normalisation, binary file handling |
| `.pre-commit-config.yaml` | Ruff lint, ruff format, mypy on every commit |
| `.envrc` | direnv hook — auto-activates virtualenv on `cd` |
| `shell.nix` | NixOS only — provides `libstdc++.so.6` |

On Windows, `.envrc` and `shell.nix` are omitted. On NixOS, `.envrc` is prefixed with `use nix shell.nix`.

---

## Removing Zenit from a project

Delete `.zenit.toml`. The project continues to work exactly as before — `main.py`, `pyproject.toml`, the database layer, and all routes have no dependency on Zenit at runtime. You lose the ability to add or remove addons cleanly, but the application itself is unaffected.

---

## Writing a new template

See [Architecture: Addons & Templates](../architecture/addons-and-templates.md) for the complete reference on template structure, injection point declaration, and the manifest format.

