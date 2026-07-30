"""
Idempotent seed script: mock users, packages, and forum posts.

Safe to run more than once - checks for existing data before inserting, so
re-running (or an accidental double-invocation via SEED_ON_STARTUP) never
duplicates records. Runnable standalone (`python -m backend.seed_data`) or
called from backend/main.py's lifespan when SEED_ON_STARTUP=true, or on
demand via the gated /api/test/seed-mock-data hook.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.database.connection import mongo_manager
from backend.services.auth_service import hash_password
from backend.services.predictive_engine import predict_delay

logger = logging.getLogger("boxdrop.seed")

SEED_MARKER_USERNAME = "demo_user"


async def seed_database(db: AsyncIOMotorDatabase) -> bool:
    """Returns True if seeding actually ran, False if seed data was already present."""
    existing = await db.users.find_one({"username": SEED_MARKER_USERNAME})
    if existing is not None:
        logger.info("Seed data already present - skipping.")
        return False

    now = datetime.now(timezone.utc)

    users = [
        {"_id": str(uuid4()), "username": "demo_user", "password_hash": hash_password("DemoPass123"), "created_at": now},
        {"_id": str(uuid4()), "username": "alex_shopper", "password_hash": hash_password("DemoPass123"), "created_at": now},
    ]
    await db.users.insert_many(users)
    demo_user_id, alex_user_id = users[0]["username"], users[1]["username"]

    package_specs = [
        # (user_id, tracking_number, carrier, status, estimated_delivery)
        (demo_user_id, "TRK-SEED-1", "DHL", "In Transit", now + timedelta(days=2)),
        (demo_user_id, "TRK-SEED-2", "Israel Post", "In Transit", now - timedelta(days=6)),  # overdue -> worker flags it high-risk
        (demo_user_id, "TRK-SEED-3", "FedEx", "Ready for Pickup", now + timedelta(days=1)),
        (alex_user_id, "TRK-SEED-4", "UPS", "Delivered", now - timedelta(days=10)),
    ]
    packages = []
    for user_id, tracking_number, carrier, pkg_status, estimated_delivery in package_specs:
        prediction = predict_delay(carrier, estimated_delivery)
        packages.append(
            {
                "_id": str(uuid4()),
                "user_id": user_id,
                "tracking_number": tracking_number,
                "carrier": carrier,
                "status": pkg_status,
                "pickup_location": "Ullmann Building" if pkg_status == "Ready for Pickup" else None,
                "estimated_delivery": estimated_delivery,
                "arrival_date": now if pkg_status == "Ready for Pickup" else None,
                "created_at": now,
                "delay_probability": prediction.delay_probability,
                "risk_level": prediction.risk_level,
                "contributing_factors": prediction.contributing_factors,
            }
        )
    await db.packages.insert_many(packages)

    root_post_id = str(uuid4())
    forum_posts = [
        {
            "_id": root_post_id,
            "author_user_id": demo_user_id,
            "anonymous": False,
            "content": "Has anyone else had DHL packages stuck 'In Transit' for over a week?",
            "reply_to": None,
            "created_at": now,
        },
        {
            "_id": str(uuid4()),
            "author_user_id": alex_user_id,
            "anonymous": True,
            "content": "Yes, happened to me last month with Israel Post around the holidays.",
            "reply_to": root_post_id,
            "created_at": now + timedelta(minutes=5),
        },
    ]
    await db.forum_posts.insert_many(forum_posts)

    logger.info("Seeded %d users, %d packages, %d forum posts.", len(users), len(packages), len(forum_posts))
    return True


async def _main() -> None:
    await mongo_manager.connect()
    try:
        await seed_database(mongo_manager.database)
    finally:
        await mongo_manager.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_main())
