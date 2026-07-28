"""
Request logging + correlation ID injection middleware.
"""
import time
import uuid
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request

logger = logging.getLogger("safeher.access")

# Paths that skip auth logging verbosity
HEALTH_PATHS = {"/health", "/", "/docs", "/redoc", "/openapi.json"}


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = str(uuid.uuid4())[:8]
        request.state.request_id = request_id
        start = time.perf_counter()

        response = await call_next(request)

        duration_ms = (time.perf_counter() - start) * 1000
        if request.url.path not in HEALTH_PATHS:
            logger.info(
                "[%s] %s %s — %d (%.1fms)",
                request_id,
                request.method,
                request.url.path,
                response.status_code,
                duration_ms,
            )

        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time"] = f"{duration_ms:.2f}ms"
        return response
