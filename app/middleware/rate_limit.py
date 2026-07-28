"""
Rate-limiting middleware using Redis sliding window.
Protects all routes, with stricter limits for SOS endpoints.
"""
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from fastapi import Request
from app.database.redis_client import is_rate_limited
from app.config import settings

logger = logging.getLogger("safeher.ratelimit")

SOS_PATHS = ["/api/v1/sos", "/api/v1/emergency"]


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        client_ip = request.client.host if request.client else "unknown"
        path = request.url.path

        # Determine limit
        if any(path.startswith(sos) for sos in SOS_PATHS):
            limit = settings.RATE_LIMIT_SOS_REQUESTS
        else:
            limit = settings.RATE_LIMIT_REQUESTS

        key = f"ratelimit:{client_ip}:{path}"
        window = settings.RATE_LIMIT_WINDOW_SECONDS

        if await is_rate_limited(key, limit, window):
            logger.warning("Rate limit exceeded — IP: %s, Path: %s", client_ip, path)
            return JSONResponse(
                status_code=429,
                content={"error": "Rate limit exceeded", "detail": f"Max {limit} requests per {window}s"},
            )

        return await call_next(request)
