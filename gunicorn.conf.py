"""
Gunicorn configuration for production deployment.
Target: 5000 concurrent users across 4 async workers.

Worker math:
  4 workers × 1000 async green-threads (uvicorn) = 4000+ concurrent I/O ops
  Each worker holds MongoDB pool of 100 connections → 400 total DB slots
  Redis handles pub/sub fan-out across workers.
"""
import multiprocessing
import os

# ── Worker configuration ──────────────────────────────────────────────────────
worker_class = "uvicorn.workers.UvicornWorker"
workers = int(os.getenv("WORKERS", min(multiprocessing.cpu_count() * 2, 8)))
threads = 1  # UvicornWorker is single-threaded async
worker_connections = 1500  # per worker — total ~6000 at 4 workers

# ── Networking ────────────────────────────────────────────────────────────────
bind = f"0.0.0.0:{os.getenv('PORT', '8000')}"
backlog = 2048

# ── Timeouts ─────────────────────────────────────────────────────────────────
timeout = 120          # worker silent timeout
graceful_timeout = 30  # graceful worker shutdown
keepalive = 65         # keep-alive for load balancer health checks

# ── Logging ───────────────────────────────────────────────────────────────────
loglevel = os.getenv("LOG_LEVEL", "info")
access_log = "-"
error_log = "-"
accesslog = None       # handled by our RequestLoggingMiddleware

# ── Process management ────────────────────────────────────────────────────────
preload_app = True     # load app once before forking (saves memory)
max_requests = 5000    # recycle workers to prevent memory leaks
max_requests_jitter = 500
daemon = False

# ── Security ─────────────────────────────────────────────────────────────────
limit_request_line = 8190
limit_request_fields = 100
forwarded_allow_ips = "*"  # trust X-Forwarded-For from reverse proxy
