"""Redis connection helper.

Usage:
    from mypackage.integrations.redis import get_redis

    @router.get("/example")
    async def example(redis: Redis = Depends(get_redis)) -> dict:
        await redis.set("key", "value", ex=60)
        value = await redis.get("key")
        return {"value": value}
"""

import os
from collections.abc import AsyncGenerator

import redis.asyncio as aioredis
from redis.asyncio import Redis

# REDIS_URL is read from the environment directly.
# For FastAPI projects, settings.py exposes this via the redis_url field,
# which is set from the REDIS_URL environment variable.
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

_pool: aioredis.ConnectionPool | None = None


def _get_pool() -> aioredis.ConnectionPool:
    global _pool
    if _pool is None:
        _pool = aioredis.ConnectionPool.from_url(
            REDIS_URL,
            decode_responses=True,
        )
    return _pool


async def get_redis() -> AsyncGenerator[Redis]:
    """FastAPI dependency that yields a Redis client from the shared pool."""
    async with aioredis.Redis(connection_pool=_get_pool()) as client:
        yield client


async def close_redis() -> None:
    """Call from lifespan shutdown to cleanly drain the pool."""
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None
