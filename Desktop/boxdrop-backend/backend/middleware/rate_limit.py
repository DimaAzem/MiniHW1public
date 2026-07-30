"""
Basic rate-limiting middleware: a hand-rolled in-memory sliding window.

No new dependency for this - a sliding window keyed by client IP is about
30 lines of Python and is trivial to explain and verify. Not suitable for a
multi-process/multi-instance deployment (state isn't shared across workers),
which is a reasonable limitation for a single-container course project.
"""

import time
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

# Endpoints exempt from rate limiting - health checks (polled every 10s by
# docker-compose) and API docs should never be throttled.
EXEMPT_PATHS = {"/", "/api/health", "/docs", "/openapi.json", "/redoc"}


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_requests: int = 60, window_seconds: float = 10.0) -> None:
        super().__init__(app)
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict[str, deque] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next):
        if request.url.path in EXEMPT_PATHS:
            return await call_next(request)

        client_key = request.client.host if request.client else "unknown"
        now = time.monotonic()
        hits = self._hits[client_key]

        while hits and now - hits[0] > self.window_seconds:
            hits.popleft()

        if len(hits) >= self.max_requests:
            return JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "code": "RATE_LIMITED",
                        "message": f"Too many requests - limit is {self.max_requests} per {self.window_seconds:.0f}s. Please slow down.",
                    }
                },
            )

        hits.append(now)
        return await call_next(request)
