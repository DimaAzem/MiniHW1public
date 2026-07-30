"""
BoxDrop API - application entrypoint.

Wires together the FastAPI app: lifespan-managed MongoDB connection, custom
OpenAPI metadata, CORS, a rate-limiting middleware, and global exception
handlers that guarantee no route ever leaks a raw stack trace to a client.
"""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.api.analytics import router as analytics_router
from backend.api.auth import InvalidCredentialsError, UsernameTakenError
from backend.api.auth import router as auth_router
from backend.api.exceptions import router as exceptions_router
from backend.api.forum import ForumRateLimitExceededError
from backend.api.forum import router as forum_router
from backend.api.packages import DuplicateTrackingNumberError, PackageNotFoundError
from backend.api.packages import router as packages_router
from backend.api.parser import router as parser_router
from backend.api.routing import NoPickupLocationsError
from backend.api.routing import router as routing_router
from backend.database.connection import DatabaseUnavailableError, mongo_manager
from backend.middleware.rate_limit import RateLimitMiddleware
from backend.seed_data import seed_database
from backend.services.auth_service import InvalidTokenError

ENABLE_TEST_ENDPOINTS = os.getenv("ENABLE_TEST_ENDPOINTS", "false").lower() == "true"
SEED_ON_STARTUP = os.getenv("SEED_ON_STARTUP", "false").lower() == "true"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("boxdrop")

TAGS_METADATA = [
    {
        "name": "auth",
        "description": "User registration and login. Passwords are bcrypt-hashed; sessions are signed JWTs.",
    },
    {
        "name": "packages",
        "description": "User-scoped package CRUD, each enriched with a live delay prediction.",
    },
    {
        "name": "routing",
        "description": "Smart Pickup Route Optimizer - greedy TSP heuristic over ready-for-pickup packages.",
    },
    {
        "name": "analytics",
        "description": "Predictive Carrier Analytics - carrier delay forecasting and dynamic ETA.",
    },
    {
        "name": "parser",
        "description": "Order/shipping-text parsing with a validation guardrail and per-user preference learning.",
    },
    {
        "name": "exceptions",
        "description": "Flagged high-risk packages, written by the background worker (backend/worker.py).",
    },
    {
        "name": "forum",
        "description": "Real-time community forum - REST posts/replies plus a WebSocket feed, with anonymity support.",
    },
    {
        "name": "test-hooks",
        "description": "TEST ONLY - only present when ENABLE_TEST_ENDPOINTS=true. Never enable in a real deployment.",
    },
    {
        "name": "system",
        "description": "Operational endpoints: health and readiness checks.",
    },
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage the MongoDB connection for the lifetime of the application."""
    logger.info("Starting BoxDrop API...")
    await mongo_manager.connect()
    if SEED_ON_STARTUP:
        await seed_database(mongo_manager.database)
    if ENABLE_TEST_ENDPOINTS:
        logger.warning("ENABLE_TEST_ENDPOINTS is on - /api/test/* routes are live. Never set this in a real deployment.")
    yield
    logger.info("Shutting down BoxDrop API...")
    await mongo_manager.close()


app = FastAPI(
    title="BoxDrop API",
    description=(
        "Production-grade backend for package tracking, smart pickup routing, and "
        "predictive carrier analytics. Built for the Technion software engineering course."
    ),
    version="2.0.0",
    contact={"name": "BoxDrop Engineering"},
    license_info={"name": "MIT"},
    openapi_tags=TAGS_METADATA,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RateLimitMiddleware, max_requests=300, window_seconds=10.0)

app.include_router(auth_router, prefix="/api")
app.include_router(packages_router, prefix="/api")
app.include_router(routing_router, prefix="/api")
app.include_router(analytics_router, prefix="/api")
app.include_router(parser_router, prefix="/api")
app.include_router(exceptions_router, prefix="/api")
app.include_router(forum_router, prefix="/api")

if ENABLE_TEST_ENDPOINTS:
    # Only imported/registered under the flag - when it's off, these routes
    # don't exist on the app at all (a real 404, not a permission check).
    from backend.api.test_hooks import router as test_hooks_router

    app.include_router(test_hooks_router, prefix="/api")


# ---------------------------------------------------------------------------
# Global exception handlers
# ---------------------------------------------------------------------------
# Every handler below returns a consistent {"error": {...}} envelope and
# never re-raises, so clients never see a raw traceback regardless of what
# fails inside a route.
def _error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
    )


@app.exception_handler(PackageNotFoundError)
async def package_not_found_handler(request: Request, exc: PackageNotFoundError) -> JSONResponse:
    return _error_response(status.HTTP_404_NOT_FOUND, "PACKAGE_NOT_FOUND", str(exc))


@app.exception_handler(DuplicateTrackingNumberError)
async def duplicate_tracking_number_handler(request: Request, exc: DuplicateTrackingNumberError) -> JSONResponse:
    return _error_response(status.HTTP_409_CONFLICT, "DUPLICATE_TRACKING_NUMBER", str(exc))


@app.exception_handler(NoPickupLocationsError)
async def no_pickup_locations_handler(request: Request, exc: NoPickupLocationsError) -> JSONResponse:
    return _error_response(status.HTTP_400_BAD_REQUEST, "NO_PICKUP_LOCATIONS", str(exc))


@app.exception_handler(UsernameTakenError)
async def username_taken_handler(request: Request, exc: UsernameTakenError) -> JSONResponse:
    return _error_response(status.HTTP_409_CONFLICT, "USERNAME_TAKEN", str(exc))


@app.exception_handler(InvalidCredentialsError)
async def invalid_credentials_handler(request: Request, exc: InvalidCredentialsError) -> JSONResponse:
    return _error_response(status.HTTP_401_UNAUTHORIZED, "INVALID_CREDENTIALS", str(exc))


@app.exception_handler(InvalidTokenError)
async def invalid_token_handler(request: Request, exc: InvalidTokenError) -> JSONResponse:
    return _error_response(status.HTTP_401_UNAUTHORIZED, "INVALID_TOKEN", str(exc))


@app.exception_handler(ForumRateLimitExceededError)
async def forum_rate_limit_handler(request: Request, exc: ForumRateLimitExceededError) -> JSONResponse:
    return _error_response(status.HTTP_429_TOO_MANY_REQUESTS, "FORUM_RATE_LIMITED", str(exc))


@app.exception_handler(DatabaseUnavailableError)
async def database_unavailable_handler(request: Request, exc: DatabaseUnavailableError) -> JSONResponse:
    logger.error("Database unavailable: %s", exc)
    return _error_response(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "DATABASE_UNAVAILABLE",
        "The database is temporarily unavailable. Please try again shortly.",
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "One or more fields failed validation.",
                # jsonable_encoder, not exc.errors() directly: Pydantic v2 puts the raw
                # exception object in ctx.error for custom validators, which plain
                # json.dumps can't serialize.
                "details": jsonable_encoder(exc.errors()),
            }
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all safety net: log the real error server-side, never expose it."""
    logger.exception("Unhandled exception while processing %s %s", request.method, request.url)
    return _error_response(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "INTERNAL_SERVER_ERROR",
        "An unexpected error occurred. Please try again later.",
    )


@app.get("/", tags=["system"], summary="API root")
async def read_root() -> dict:
    return {"status": "BoxDrop API is running", "docs": "/docs"}


@app.get("/api/health", tags=["system"], summary="Health check")
async def health_check() -> dict:
    db_connected = await mongo_manager.ping()
    return {
        "status": "healthy" if db_connected else "degraded",
        "database": "connected" if db_connected else "disconnected",
    }
