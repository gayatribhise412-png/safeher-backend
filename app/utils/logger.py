"""
Structured logging setup — JSON in production, coloured text in dev.
"""
import logging
import sys
from app.config import settings


def setup_logging() -> None:
    level = logging.DEBUG if settings.DEBUG else logging.INFO
    fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"

    if settings.ENVIRONMENT == "production":
        try:
            import json_log_formatter
            handler = logging.StreamHandler(sys.stdout)
            handler.setFormatter(json_log_formatter.JSONFormatter())
        except ImportError:
            handler = logging.StreamHandler(sys.stdout)
            handler.setFormatter(logging.Formatter(fmt))
    else:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(fmt, datefmt="%Y-%m-%d %H:%M:%S"))

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # Quiet noisy libs
    for noisy in ("uvicorn.access", "motor", "pymongo"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
