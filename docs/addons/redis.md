# redis

The `redis` addon adds an async Redis connection helper with connection pooling. Works with both templates. Required by the `celery` addon.

---

## When to use it

Choose `redis` when your project needs:

- Caching layer for API responses or computed data
- Session storage
- Rate limiting backends
- Pub/sub messaging
- Celery broker/backend (required by the `celery` addon)

---

## What it adds

### Files

| File | Purpose |
|---|---|
| `src/{{pkg_name}}/integrations/__init__.py` | Package marker |
| `src/{{pkg_name}}/integrations/redis.py` | Connection pool, `get_redis()` dependency, `close_redis()` cleanup |

### Redis helper API

```python
async def get_redis() -> AsyncGenerator[Redis]:
    """FastAPI dependency that yields a Redis client from the shared pool."""

async def close_redis() -> None:
    """Call from lifespan shutdown to cleanly drain the pool."""
```

Usage in a route:

```python
from {{pkg_name}}.integrations.redis import get_redis
from redis.asyncio import Redis

@router.get("/cache")
async def get_cache(redis: Redis = Depends(get_redis)) -> dict:
    value = await redis.get("my-key")
    return {"value": value}
```

### Compose service

Adds a `redis` service to `compose.yml`:

- Image: `redis:7-alpine`
- Port: `6379:6379`
- Volume: `redis-data:/data` (persistent, AOF enabled)
- Health check: `redis-cli ping`

### Settings field

Injects into `settings_fields`:

```python
redis_url: str = "redis://localhost:6379/0"
```

### Environment variables

| Key | Default |
|---|---|
| `REDIS_URL` | `redis://localhost:6379/0` |

### Dependencies

- `redis>=5` - Redis Python client
- `hiredis` - C parser for performance
- `python-dotenv` - `.env` file loading

### Dev dependencies

- `fakeredis` - In-memory Redis for testing

### Just recipes

| Recipe | Command |
|---|---|
| `just redis-up` | Start Redis container |
| `just redis-down` | Stop Redis container |
| `just redis-cli` | Open redis-cli |

---

## Post-installation

```bash
just redis-up   # Start the Redis container
```

For `fastapi` projects, the connection pool is managed automatically via lifespan hooks. For `blank` projects, integrate `close_redis()` into your shutdown logic manually.

---

## Testing with fakeredis

```python
import fakeredis.aioredis

@pytest.fixture
def fake_redis():
    return fakeredis.aioredis.FakeRedis()
```

---

## Removing the addon

`zenit remove redis` will:

- Delete `src/{{pkg_name}}/integrations/redis.py` (and `__init__.py` if empty)
- Remove the `redis` service and `redis-data` volume from `compose.yml`
- Remove `redis_url` from settings
- Remove `REDIS_URL` from `.env` and `.env.example`
- Remove `redis>=5`, `hiredis`, and `fakeredis` from `pyproject.toml`
- Remove redis just recipes

> [!NOTE]
> If the `celery` addon is installed, it depends on `redis`. Remove `celery` first.
