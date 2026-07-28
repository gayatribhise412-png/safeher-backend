"""
MongoDB async connection — Motor driver.
Single shared client, pooled per settings (max_pool_size=100 per worker).
Call connect_db() on startup and close_db() on shutdown from main.py.
"""
import logging
from typing import Optional
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo import IndexModel, ASCENDING, DESCENDING, GEOSPHERE
from app.config import settings

logger = logging.getLogger("safeher.db")

_client: Optional[AsyncIOMotorClient] = None
_db: Optional[AsyncIOMotorDatabase] = None


async def connect_db() -> None:
    """Create Motor client and ensure all indexes exist."""
    global _client, _db
    logger.info("Connecting to MongoDB …")
    _client = AsyncIOMotorClient(
        settings.MONGODB_URI,
        maxPoolSize=settings.MONGODB_MAX_POOL_SIZE,
        minPoolSize=settings.MONGODB_MIN_POOL_SIZE,
        maxIdleTimeMS=settings.MONGODB_MAX_IDLE_TIME_MS,
        serverSelectionTimeoutMS=5_000,
        connectTimeoutMS=5_000,
        socketTimeoutMS=30_000,
        retryWrites=True,
        w="majority",
    )
    _db = _client[settings.MONGODB_DB_NAME]
    await _ensure_indexes()
    logger.info("MongoDB connected — DB: %s", settings.MONGODB_DB_NAME)


async def close_db() -> None:
    global _client
    if _client:
        _client.close()
        logger.info("MongoDB connection closed")


def get_db() -> AsyncIOMotorDatabase:
    if _db is None:
        raise RuntimeError("Database not initialised. Call connect_db() first.")
    return _db


# ── Collection helpers ────────────────────────────────────────────────────────

def get_collection(name: str):
    return get_db()[name]


# ── Index creation ─────────────────────────────────────────────────────────────

async def _ensure_indexes() -> None:
    """
    Create all required indexes at startup.
    Idempotent — safe to run every time.
    """
    db = get_db()

    # users
    await db.users.create_indexes([
        IndexModel([("email", ASCENDING)], unique=True, name="email_unique"),
        IndexModel([("phone", ASCENDING)], unique=True, sparse=True, name="phone_unique"),
        IndexModel([("created_at", DESCENDING)], name="created_at_desc"),
        IndexModel([("is_active", ASCENDING)], name="is_active"),
    ])

    # sos_alerts
    await db.sos_alerts.create_indexes([
        IndexModel([("user_id", ASCENDING)], name="sos_user_id"),
        IndexModel([("status", ASCENDING)], name="sos_status"),
        IndexModel([("created_at", DESCENDING)], name="sos_created_at"),
        IndexModel([("location", GEOSPHERE)], name="sos_geo", sparse=True),
    ])

    # locations (live tracking — time-series-like)
    await db.locations.create_indexes([
        IndexModel([("user_id", ASCENDING), ("timestamp", DESCENDING)], name="loc_user_time"),
        IndexModel([("coordinates", GEOSPHERE)], name="loc_geo"),
        IndexModel([("timestamp", DESCENDING)], expireAfterSeconds=86_400, name="loc_ttl"),  # 24-hour TTL
    ])

    # notifications
    await db.notifications.create_indexes([
        IndexModel([("user_id", ASCENDING), ("created_at", DESCENDING)], name="notif_user_time"),
        IndexModel([("is_read", ASCENDING)], name="notif_read"),
    ])

    # emergency_contacts
    await db.emergency_contacts.create_indexes([
        IndexModel([("user_id", ASCENDING)], name="contact_user_id"),
    ])

    # chat_sessions
    await db.chat_sessions.create_indexes([
        IndexModel([("user_id", ASCENDING), ("created_at", DESCENDING)], name="chat_user_time"),
        IndexModel([("created_at", DESCENDING)], expireAfterSeconds=2_592_000, name="chat_ttl"),  # 30-day TTL
    ])

    # voice_recordings
    await db.voice_recordings.create_indexes([
        IndexModel([("user_id", ASCENDING), ("created_at", DESCENDING)], name="voice_user_time"),
    ])

    # refresh_tokens
    await db.refresh_tokens.create_indexes([
        IndexModel([("token_hash", ASCENDING)], unique=True, name="token_hash_unique"),
        IndexModel([("expires_at", ASCENDING)], expireAfterSeconds=0, name="token_ttl"),
    ])

    logger.info("All MongoDB indexes verified/created")
