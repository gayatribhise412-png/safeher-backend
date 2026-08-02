"""
MongoDB async connection - Motor driver.
"""
import logging
import os
from typing import Optional
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

logger = logging.getLogger("safeher.db")

MONGO_URI = os.getenv("MONGO_URI")

_client: Optional[AsyncIOMotorClient] = None
_db: Optional[AsyncIOMotorDatabase] = None

async def connect_db() -> None:
    """Create Motor client and ensure all indexes exist."""
    global _client, _db
    logger.info("Connecting to MongoDB...")
    _client = AsyncIOMotorClient(MONGO_URI)
    _db = _client["safeherdb"]
    logger.info(f"MongoDB connected - DB: safeherdb")

async def close_db() -> None:
    global _client
    if _client:
        _client.close()

def get_db() -> AsyncIOMotorDatabase:
    return _db
