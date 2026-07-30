"""
Per-user carrier/vendor preference learning for the order parser.

Every time a user confirms a parsed order, we record which carrier/vendor
combination they confirmed. Future ambiguous parses for that same user fall
back to whichever carrier they've confirmed most often - a simple
frequency-based "learning" mechanism, not a trained model.
"""

from datetime import datetime, timezone
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorDatabase


async def record_confirmed_order(
    db: AsyncIOMotorDatabase, user_id: str, carrier: str, vendor: Optional[str]
) -> None:
    """Increments the confirmed-count for this (user, carrier, vendor) combination."""
    await db.user_preferences.update_one(
        {"user_id": user_id, "carrier": carrier, "vendor": vendor or ""},
        {
            "$inc": {"confirmed_count": 1},
            "$set": {"last_confirmed_at": datetime.now(timezone.utc)},
        },
        upsert=True,
    )


async def get_preferred_carrier(db: AsyncIOMotorDatabase, user_id: str) -> Optional[str]:
    """Returns the user's most-frequently-confirmed carrier, if any."""
    document = await db.user_preferences.find_one({"user_id": user_id}, sort=[("confirmed_count", -1)])
    return document["carrier"] if document else None
