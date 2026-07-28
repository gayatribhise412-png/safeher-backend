"""
Root-level entry point for Gunicorn / Docker CMD.
Usage:  gunicorn app.main:app -c gunicorn.conf.py
"""
from app.main import app  # noqa: F401 — re-exported for Gunicorn
