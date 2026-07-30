"""
Background worker: periodic risk re-scoring for in-flight packages.

Runs as its OWN process/container (docker-compose's `worker` service), not
inside the API server, so a slow scan across every user's packages never
blocks a single HTTP request. Polls MongoDB directly on an interval - no
message broker, consistent with this project's existing preference for
hand-rolled solutions over new infrastructure where the scale doesn't
warrant it (see backend/middleware/rate_limit.py for the same reasoning).

Run standalone: `python -m backend.worker`
"""

import asyncio
import logging
import os
from datetime import datetime, timezone
from uuid import uuid4

from backend.database.connection import mongo_manager
from backend.services.predictive_engine import recompute_risk_with_status

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("boxdrop.worker")

WORKER_INTERVAL_SECONDS = float(os.getenv("WORKER_INTERVAL_SECONDS", "30"))


async def rescore_in_transit_packages() -> int:
    """Re-scores every 'In Transit' package and flags new high-risk exceptions. Returns the count scanned."""
    db = mongo_manager.database
    cursor = db.packages.find({"status": "In Transit"})

    scanned = 0
    async for package in cursor:
        scanned += 1
        prediction = recompute_risk_with_status(package)
        previous_risk_level = package.get("risk_level")

        await db.packages.update_one(
            {"_id": package["_id"]},
            {
                "$set": {
                    "delay_probability": prediction.delay_probability,
                    "risk_level": prediction.risk_level,
                    "contributing_factors": prediction.contributing_factors,
                }
            },
        )

        # Only flag on a NEW crossing into "high" - avoids flooding the same
        # user with a repeat exception every single worker cycle.
        if prediction.risk_level == "high" and previous_risk_level != "high":
            await db.exceptions.insert_one(
                {
                    "_id": str(uuid4()),
                    "user_id": package["user_id"],
                    "tracking_number": package["tracking_number"],
                    "risk_score": prediction.delay_probability,
                    "reason": "; ".join(prediction.contributing_factors),
                    "flagged_at": datetime.now(timezone.utc),
                }
            )
            logger.info(
                "Flagged exception for %s (user=%s, risk=%.0f%%)",
                package["tracking_number"],
                package["user_id"],
                prediction.delay_probability * 100,
            )

    return scanned


async def run_worker_loop() -> None:
    await mongo_manager.connect()
    logger.info("BoxDrop worker started, polling every %ss", WORKER_INTERVAL_SECONDS)
    try:
        while True:
            try:
                scanned = await rescore_in_transit_packages()
                logger.info("Worker cycle complete: re-scored %d in-transit package(s)", scanned)
            except Exception:
                logger.exception("Worker cycle failed - will retry next interval")
            await asyncio.sleep(WORKER_INTERVAL_SECONDS)
    finally:
        await mongo_manager.close()


if __name__ == "__main__":
    asyncio.run(run_worker_loop())
