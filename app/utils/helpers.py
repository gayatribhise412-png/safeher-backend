"""
Shared utility functions.
"""
import re
import math
import hashlib
import logging
from datetime import datetime, timezone
from typing import Any
from bson import ObjectId

logger = logging.getLogger("safeher.helpers")


# ── ObjectId / serialisation ──────────────────────────────────────────────────

def to_str_id(doc: dict) -> dict:
    """Convert MongoDB _id ObjectId to string in-place."""
    if doc and "_id" in doc:
        doc["id"] = str(doc.pop("_id"))
    return doc


def serialize_doc(doc: Any) -> Any:
    """Recursively convert ObjectId and datetime to JSON-safe types."""
    if isinstance(doc, dict):
        return {k: serialize_doc(v) for k, v in doc.items()}
    if isinstance(doc, list):
        return [serialize_doc(i) for i in doc]
    if isinstance(doc, ObjectId):
        return str(doc)
    if isinstance(doc, datetime):
        return doc.isoformat()
    return doc


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Validation ────────────────────────────────────────────────────────────────

PHONE_RE = re.compile(r"^\+?[1-9]\d{6,14}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def is_valid_phone(phone: str) -> bool:
    return bool(PHONE_RE.match(phone.strip()))


def is_valid_email(email: str) -> bool:
    return bool(EMAIL_RE.match(email.strip().lower()))


# ── Geo ───────────────────────────────────────────────────────────────────────

def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres."""
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def build_geo_point(lat: float, lng: float) -> dict:
    """GeoJSON Point for MongoDB $near / GEO2DSPHERE queries."""
    return {"type": "Point", "coordinates": [lng, lat]}


# ── Hashing ───────────────────────────────────────────────────────────────────

def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


# ── Response builder ──────────────────────────────────────────────────────────

def success(data: Any = None, message: str = "Success") -> dict:
    return {"success": True, "message": message, "data": data}


def error(message: str, code: int = 400) -> dict:
    return {"success": False, "message": message, "code": code}
