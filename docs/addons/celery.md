# celery

> **Requires:** `redis` addon

The `celery` addon adds a Celery worker and beat scheduler to a project, backed by Redis. It provides the infrastructure for background tasks, periodic jobs, and distributed task queues.

---

## When to use it

Choose `celery` when your project needs:

- Background task execution outside the request/response cycle
- Periodic scheduled tasks via the beat scheduler
- Distributed task queues across multiple workers
- Flower monitoring UI for task inspection

---

## What it adds

### Files

| File | Purpose |
|---|---|
| `src/{{pkg_name}}/tasks/__init__.py` | Package marker |
| `src/{{pkg_name}}/tasks/celery_app.py` | Celery app configuration with Redis broker/backend |
| `src/{{pkg_name}}/tasks/example_tasks.py` | Example task (`add`) as a starting point |

### Celery configuration

The generated `celery_app.py` configures:

- **Broker:** Redis URL from `REDIS_URL` environment variable
- **Backend:** Same Redis instance for result storage
- **Serializer:** JSON for tasks and results
- **Timezone:** UTC
- **Include:** `{{pkg_name}}.tasks.example_tasks` (add your own modules here)

### Compose services

Adds two services to `compose.yml`:

| Service | Purpose |
|---|---|
| `celery-worker` | Runs Celery worker process |
| `celery-beat` | Runs Celery beat scheduler for periodic tasks |

Both services:
- Build from the project Dockerfile
- Share the `.env` file with the app
- Depend on the `redis` service being healthy
- Use Docker Compose watch mode for live code syncing

### Dependencies

- `celery[redis]>=5` — Celery with Redis support
- `flower` — Web-based monitoring and administration

### Dev dependencies

- `pytest-celery` — Testing utilities for Celery tasks

### Just recipes

| Recipe | Command |
|---|---|
| `just celery-up` | Start celery worker and beat scheduler |
| `just celery-down` | Stop celery worker and beat |
| `just celery-flower` | Open Flower monitoring UI on port 5555 |
| `just celery-logs` | Tail celery worker logs |

---

## Usage

### Defining tasks

Add task functions to any module under `tasks/`:

```python
from {{pkg_name}}.tasks.celery_app import celery_app

@celery_app.task
def send_email(to: str, subject: str, body: str) -> None:
    # Implementation here
    pass
```

### Calling tasks

```python
from {{pkg_name}}.tasks.example_tasks import add

# Async (fire and forget)
add.delay(1, 2)

# Sync (wait for result)
result = add.delay(1, 2)
print(result.get(timeout=10))
```

### Periodic tasks

Uncomment and modify the `beat_schedule` in `celery_app.py`:

```python
beat_schedule = {
    "cleanup-every-hour": {
        "task": "my_project.tasks.cleanup.old_records",
        "schedule": 3600.0,
    },
}
```

---

## Post-installation

After adding the addon:

```bash
just celery-up     # Start worker and beat
just celery-logs   # Watch worker output
just celery-flower # Open monitoring UI at http://localhost:5555
```

---

## Removing the addon

`zenit remove celery` will:

- Delete the `tasks/` directory and all its files
- Remove celery services from `compose.yml`
- Remove `celery[redis]` and `flower` from `pyproject.toml`
- Remove `pytest-celery` from dev dependencies
- Remove all celery just recipes

Any custom tasks you wrote in `tasks/` will be deleted. Back them up before removing if you want to keep them.
