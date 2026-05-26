# sentry

The `sentry` addon adds Sentry error tracking and performance monitoring. Works with both templates. Initialises the Sentry SDK on application startup and captures exceptions, performance traces, and error context automatically.

---

## When to use it

Choose `sentry` when you want:

- Automatic error reporting with stack traces
- Performance monitoring for HTTP requests and database queries
- Release tracking and error aggregation
- Alerts for new or regressed issues

---

## What it adds

### Files

| File | Purpose |
|---|---|
| `src/{{pkg_name}}/integrations/__init__.py` | Package marker (if not present) |
| `src/{{pkg_name}}/integrations/sentry.py` | Sentry SDK initialisation with conditional enablement |

### Sentry initialisation

The generated `sentry.py`:

- Reads `SENTRY_DSN` from environment — no-ops when empty (safe for local dev)
- For `fastapi` projects: includes `FastApiIntegration` and `SqlalchemyIntegration`
- For `blank` projects: basic Sentry SDK init

### Settings fields

```python
sentry_dsn: str = ""
sentry_environment: str = "development"
```

### Environment variables

| Key | Default | Description |
|---|---|---|
| `SENTRY_DSN` | `""` | Sentry project DSN (empty = disabled) |
| `SENTRY_ENVIRONMENT` | `development` | Environment tag |

### Dependencies

- `sentry-sdk[fastapi]` — Sentry SDK with FastAPI integration
- `python-dotenv` — `.env` file loading

### Just recipes

| Recipe | Command |
|---|---|
| `just sentry-check` | Print installed sentry-sdk version |
| `just sentry-test` | Test Sentry initialisation and DSN configuration |

### Startup wiring

- **FastAPI:** Injects `init_sentry()` into `lifespan_startup` in `lifecycle.py`
- **Blank:** Injects `init_sentry()` into `main()` before the return statement

---

## Configuration

### Getting a DSN

1. Create a project at [sentry.io](https://sentry.io)
2. Go to Settings → Projects → [your project] → Client Keys (DSN)
3. Add to `.env`:

```bash
SENTRY_DSN=https://xxx@yyy.ingest.sentry.io/zzz
SENTRY_ENVIRONMENT=production
```

Leave `SENTRY_DSN` empty during local development. Sentry will be silently disabled.

### Performance monitoring

The default configuration samples 100% of traces and profiles. Adjust in production by editing `traces_sample_rate` and `profiles_sample_rate` in `sentry.py`.

---

## Post-installation

```bash
just sentry-test   # Verify Sentry is configured correctly
```

---

## Removing the addon

`zenit remove sentry` will:

- Delete `src/{{pkg_name}}/integrations/sentry.py`
- Remove `init_sentry()` calls from `lifecycle.py` (fastapi) or `main.py` (blank)
- Remove `sentry_dsn` and `sentry_environment` from settings
- Remove `SENTRY_DSN` and `SENTRY_ENVIRONMENT` from `.env` and `.env.example`
- Remove `sentry-sdk[fastapi]` from `pyproject.toml`
- Remove sentry just recipes
