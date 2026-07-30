"""
Async MongoDB connection lifecycle management.

Wraps a Motor (AsyncIOMotorClient) connection in a small manager class so the
rest of the application never touches driver internals directly. The manager
is created once at FastAPI startup (see ``backend.main``'s lifespan handler)
and torn down cleanly at shutdown, which avoids leaking sockets between test
runs and container restarts.
"""

import logging
import os
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo.errors import PyMongoError

logger = logging.getLogger("boxdrop.database")

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "boxdrop_db")

# How many times to retry the initial connection before giving up. Container
# orchestration (docker-compose) can start the API slightly before Mongo is
# ready to accept connections, so a short retry loop is cheap insurance.
CONNECT_RETRIES = int(os.getenv("MONGO_CONNECT_RETRIES", "5"))
CONNECT_RETRY_DELAY_SECONDS = float(os.getenv("MONGO_CONNECT_RETRY_DELAY", "2"))


class DatabaseUnavailableError(RuntimeError):
    """Raised when the MongoDB connection has not been established yet."""


class MongoManager:
    """Owns the lifecycle of a single Motor client for the application."""

    def __init__(self) -> None:
        self._client: Optional[AsyncIOMotorClient] = None
        self._db: Optional[AsyncIOMotorDatabase] = None

    async def connect(self) -> None:
        """Open the client connection and verify it with a ping, retrying on failure."""
        import asyncio

        last_error: Optional[Exception] = None
        for attempt in range(1, CONNECT_RETRIES + 1):
            try:
                self._client = AsyncIOMotorClient(
                    MONGO_URI,
                    serverSelectionTimeoutMS=5000,
                )
                await self._client.admin.command("ping")
                self._db = self._client[MONGO_DB_NAME]
                await self._ensure_indexes()
                logger.info("Connected to MongoDB at %s (db=%s)", MONGO_URI, MONGO_DB_NAME)
                return
            except PyMongoError as exc:
                last_error = exc
                logger.warning(
                    "MongoDB connection attempt %s/%s failed: %s",
                    attempt,
                    CONNECT_RETRIES,
                    exc,
                )
                if attempt < CONNECT_RETRIES:
                    await asyncio.sleep(CONNECT_RETRY_DELAY_SECONDS)

        raise DatabaseUnavailableError(
            f"Could not connect to MongoDB after {CONNECT_RETRIES} attempts"
        ) from last_error

    async def _ensure_indexes(self) -> None:
        """Create indexes required for correctness and lookup performance."""
        if self._db is None:
            return
        await self._db.packages.create_index([("user_id", 1), ("tracking_number", 1)], unique=True)
        await self._db.packages.create_index("user_id")
        await self._db.packages.create_index("status")
        await self._db.packages.create_index("created_at")
        await self._db.users.create_index("username", unique=True)
        await self._db.user_preferences.create_index([("user_id", 1), ("carrier", 1), ("vendor", 1)], unique=True)
        await self._db.forum_posts.create_index("created_at")
        await self._db.forum_posts.create_index("reply_to")
        await self._db.exceptions.create_index([("user_id", 1), ("flagged_at", -1)])
        await self._db.exceptions.create_index("tracking_number")

    async def close(self) -> None:
        """Close the underlying client. Safe to call even if never connected."""
        if self._client is not None:
            self._client.close()
            logger.info("MongoDB connection closed")
            self._client = None
            self._db = None

    async def ping(self) -> bool:
        """Return True if the database responds to a ping, False otherwise."""
        if self._client is None:
            return False
        try:
            await self._client.admin.command("ping")
            return True
        except PyMongoError:
            return False

    @property
    def database(self) -> AsyncIOMotorDatabase:
        if self._db is None:
            raise DatabaseUnavailableError(
                "Database connection has not been initialized. "
                "Ensure the application lifespan startup has run."
            )
        return self._db


# Module-level singleton shared across the app's lifetime.
mongo_manager = MongoManager()


def get_database() -> AsyncIOMotorDatabase:
    """FastAPI dependency that yields the active database handle."""
    return mongo_manager.database
