"""
SafeHer FastAPI application entry point.

Design targets:
  • 5000 concurrent users — 4 Uvicorn workers × 100-connection MongoDB pool = 400 DB slots,
    plus Redis pub/sub for WebSocket fan-out across workers.
  • Fully async I/O — Motor (MongoDB), redis.asyncio, httpx.
  • Rate limiting per IP via Redis sliding window.
  • JWT + bcrypt auth, refresh-token rotation, token blacklist.
  • Graceful startup/shutdown with resource cleanup.
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.utils.logger import setup_logging
from app.database.mongodb import connect_db, close_db
from app.database.redis_client import connect_redis, close_redis
from app.middleware import RateLimitMiddleware, RequestLoggingMiddleware
from app.api import api_router
from app.websocket import ws_router

# ── Logging must be configured before any other import that logs ──────────────
setup_logging()
logger = logging.getLogger("safeher.main")


# ── Lifespan (startup / shutdown) ─────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=" * 60)
    logger.info("Starting %s v%s [%s]", settings.APP_NAME, settings.APP_VERSION, settings.ENVIRONMENT)
    logger.info("=" * 60)

    # Connect data stores
    await connect_db()
    await connect_redis()

    # Ensure ML model directory exists
    import os
    os.makedirs(settings.ML_MODELS_DIR, exist_ok=True)
    os.makedirs("uploads", exist_ok=True)

    logger.info("All resources initialised — ready to serve requests")
    yield

    # Graceful shutdown
    logger.info("Shutting down — closing connections …")
    await close_db()
    await close_redis()
    logger.info("Shutdown complete")


# ── Application factory ───────────────────────────────────────────────────────

def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description=(
            "SafeHer — Women's Safety Platform API.\n\n"
            "Features: SOS alerts, live GPS tracking, AI chatbot (Aria), "
            "voice distress detection, emergency contacts, fake call, and more.\n\n"
            "All endpoints (except `/health` and public tracking links) require Bearer JWT."
        ),
        docs_url="/docs" if settings.DEBUG or settings.ENVIRONMENT != "production" else None,
        redoc_url="/redoc" if settings.DEBUG or settings.ENVIRONMENT != "production" else None,
        openapi_url="/openapi.json" if settings.ENVIRONMENT != "production" else None,
        lifespan=lifespan,
    )

    # ── Middleware stack (order matters — outermost runs first) ────────────────
    app.add_middleware(GZipMiddleware, minimum_size=1000)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=settings.ALLOWED_METHODS,
        allow_headers=settings.ALLOWED_HEADERS,
    )

    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(RateLimitMiddleware)

    # ── Routes ─────────────────────────────────────────────────────────────────
    app.include_router(api_router)    # /api/v1/...
    app.include_router(ws_router)     # /ws/...

    # ── Health / root ──────────────────────────────────────────────────────────

    @app.get("/", tags=["Health"], include_in_schema=False)
    async def root():
        return {"app": settings.APP_NAME, "version": settings.APP_VERSION, "status": "running"}

    @app.get("/health", tags=["Health"])
    async def health(request: Request):
        """
        Readiness probe — checks MongoDB and Redis connectivity.
        Returns HTTP 200 when healthy, 503 when degraded.
        """
        from app.database.mongodb import get_db
        from app.database.redis_client import get_redis

        checks: dict[str, str] = {}
        status_code = 200

        try:
            db = get_db()
            await db.command("ping")
            checks["mongodb"] = "ok"
        except Exception as exc:
            checks["mongodb"] = f"error: {exc}"
            status_code = 503

        try:
            r = get_redis()
            await r.ping()
            checks["redis"] = "ok"
        except Exception as exc:
            checks["redis"] = f"error: {exc}"
            status_code = 503

        checks["ws_connections"] = str(
            __import__("app.websocket", fromlist=["manager"]).manager.active_count()
        )

        return JSONResponse(
            content={
                "status": "healthy" if status_code == 200 else "degraded",
                "version": settings.APP_VERSION,
                "environment": settings.ENVIRONMENT,
                "checks": checks,
            },
            status_code=status_code,
        )

    # ── Global exception handlers ──────────────────────────────────────────────

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.exception("Unhandled exception on %s %s: %s", request.method, request.url.path, exc)
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": "Internal server error", "detail": str(exc) if settings.DEBUG else "Contact support"},
        )

    @app.exception_handler(404)
    async def not_found_handler(request: Request, exc):
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": "Endpoint not found", "path": str(request.url.path)},
        )

    return app


# ── Application instance (used by Gunicorn / uvicorn) ─────────────────────────
app = create_app()
app.add_middleware(   
     CORSMiddleware,
     allow_origins=["*"],
     allow_credentials=True,
     allow_methods=["*"],
     allow_headers=["*"],
# ── Dev runner ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.RELOAD,
        workers=1 if settings.RELOAD else settings.WORKERS,
        log_level="debug" if settings.DEBUG else "info",
        access_log=False,          # handled by our RequestLoggingMiddleware
        ws_ping_interval=settings.WS_HEARTBEAT_INTERVAL,
        ws_ping_timeout=10,
        limit_concurrency=5000,    # max concurrent requests across all workers
        backlog=2048,
    )
