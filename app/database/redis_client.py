"""
Redis async client — used for rate-limiting, pub/sub (WebSocket broadcast),
session blacklisting, and short-lived caching.
"""
import logging
from typing import Optional
import redis.asyncio as aioredis
from app.config import settings

logger = logging.getLogger("safeher.redis")

_redis: Optional[aioredis.Redis] = None


async def connect_redis() -> None:
    global _redis
    _redis = aioredis.from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
        max_connections=settings.REDIS_MAX_CONNECTIONS,
    )
    try:
        await _redis.ping()
        logger.info("Redis connected — %s", settings.REDIS_URL)
    except Exception as exc:
        logger.warning("Redis not available (%s) — rate limiting and pub/sub disabled", exc)
        # Don't crash — app will degrade gracefully


async def close_redis() -> None:
    global _redis
    if _redis:
        await _redis.aclose()
        logger.info("Redis connection closed")


def get_redis() -> aioredis.Redis:
    if _redis is None:
        raise RuntimeError("Redis not initialised. Call connect_redis() first.")
    return _redis


# ── Pub/Sub helpers (WebSocket live tracking) ──────────────────────────────────

async def publish(channel: str, message: str) -> None:
    try:
        r = get_redis()
        await r.publish(channel, message)
    except Exception:
        pass


async def subscribe(channel: str):
    r = get_redis()
    pubsub = r.pubsub()
    await pubsub.subscribe(channel)
    return pubsub


# ── Rate limit helpers ─────────────────────────────────────────────────────────

async def is_rate_limited(key: str, limit: int, window: int) -> bool:
    """Sliding window rate limiter. Returns True if request should be blocked."""
    try:
        r = get_redis()
        count = await r.incr(key)
        if count == 1:
            await r.expire(key, window)
        return count > limit
    except Exception:
        return False  # fail open when Redis is unavailable


# ── Token blacklist (logout) ───────────────────────────────────────────────────

async def blacklist_token(jti: str, ttl_seconds: int) -> None:
    try:
        r = get_redis()
        await r.setex(f"blacklist:{jti}", ttl_seconds, "1")
    except Exception:
        pass


async def is_token_blacklisted(jti: str) -> bool:
    try:
        r = get_redis()
        return bool(await r.exists(f"blacklist:{jti}"))
    except Exception:
        return False  # fail open when Redis is unavailable
