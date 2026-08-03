# github-actions

The `github-actions` addon adds a CI workflow that runs lint, type-check, and test on every push and pull request to `main`. Works with both templates.

---

## When to use it

Choose `github-actions` when you want:

- Automated CI on GitHub without manual configuration
- Consistent lint, format check, type check, and test execution
- Service containers (PostgreSQL, Redis) automatically provisioned for tests
- `uv` caching for fast dependency installation

---

## What it adds

### Files

| File | Purpose |
|---|---|
| `.github/workflows/ci.yml` | GitHub Actions workflow definition |

### Workflow triggers

The workflow runs on push to `main` and on pull requests targeting `main`.

### Job steps

1. **Checkout** - `actions/checkout@v4`
2. **Install uv** - `astral-sh/setup-uv@v4` with caching
3. **Set up Python** - `uv python install <version>` (the Python version your project was scaffolded with)
4. **Install dependencies** - `uv sync --all-extras`
5. **Run migrations** (fastapi + postgres only) - `uv run alembic upgrade head`
6. **Lint** - `uv run ruff check .`
7. **Format check** - `uv run ruff format --check .`
8. **Type check** - `uv run mypy src/`
9. **Test** - `uv run pytest -v`

### Service containers

The workflow automatically provisions service containers based on installed addons:

**PostgreSQL** (fastapi template) - `postgres:16`, port 5432, health checks configured.

**Redis** (if `redis` addon installed) - `redis:7-alpine`, port 6379, health checks configured.

### Environment variables in CI

- `DATABASE_URL` - points to the PostgreSQL service container
- `REDIS_URL` - points to the Redis service container

---

## Post-installation

Push to GitHub after adding the addon:

```bash
git add .github/workflows/ci.yml
git commit -m "Add CI workflow"
git push
```

The workflow runs automatically on the next push or PR.

---

## Customisation

The generated workflow is a solid starting point. Edit `.github/workflows/ci.yml` directly to add deployment steps, matrix builds, security scanning, or adjusted branch triggers. Zenit will not overwrite your changes.

---

## Removing the addon

`zenit remove github-actions` deletes `.github/workflows/ci.yml`. Back up the file first if you've customised it and want to keep those changes.
