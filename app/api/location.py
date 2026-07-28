"""
Location API — live tracking updates, history, nearby safe places.
Each location ping is stored with 24-hour TTL (Redis index on MongoDB).
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, Query

from app.schemas.sos import LocationUpdateRequest, NearbyPlacesRequest
from app.database.mongodb import get_collection
from app.database.redis_client import publish
from app.utils.dependencies import get_current_user
from app.utils.helpers import utcnow, serialize_doc, build_geo_point, haversine_km
from app.config import settings
from bson import ObjectId
import json

logger = logging.getLogger("safeher.location")
router = APIRouter(prefix="/location", tags=["Location & Tracking"])

# Static safe places (replace with Google Maps API in production)
SAFE_PLACES_DB = [
    {"type": "police", "name": "Andheri Police Station", "lat": 19.1136, "lng": 72.8697, "phone": "022-26201234", "open_24h": True},
    {"type": "hospital", "name": "Kokilaben Hospital", "lat": 19.1359, "lng": 72.8271, "phone": "022-30999999", "open_24h": True},
    {"type": "hospital", "name": "Lilavati Hospital", "lat": 19.0571, "lng": 72.8283, "phone": "022-26751000", "open_24h": True},
    {"type": "police", "name": "Bandra Police Station", "lat": 19.0596, "lng": 72.8295, "phone": "022-26401234", "open_24h": True},
    {"type": "shelter", "name": "SNEHA Women Shelter", "lat": 19.0760, "lng": 72.8777, "phone": "1800-111-333", "open_24h": True},
    {"type": "pharmacy", "name": "Apollo Pharmacy", "lat": 19.1100, "lng": 72.8800, "phone": "022-40047000", "open_24h": False},
    {"type": "police", "name": "Juhu Police Chowki", "lat": 19.0983, "lng": 72.8267, "phone": "022-26201122", "open_24h": True},
]


# ── Update live location ───────────────────────────────────────────────────────

@router.post("/update")
async def update_location(
    body: LocationUpdateRequest,
    current_user: dict = Depends(get_current_user),
):
    user_id = str(current_user["_id"])
    now = utcnow()

    location_doc = {
        "_id": str(ObjectId()),
        "user_id": user_id,
        "lat": body.lat,
        "lng": body.lng,
        "accuracy": body.accuracy,
        "speed": body.speed,
        "heading": body.heading,
        "session_id": body.session_id,
        "coordinates": build_geo_point(body.lat, body.lng),
        "timestamp": now,
    }

    # Store in DB (TTL index auto-deletes after 24h)
    col = get_collection("locations")
    await col.insert_one(location_doc)

    # Update user's last known location
    users = get_collection("users")
    await users.update_one(
        {"_id": user_id},
        {"$set": {
            "last_location": {"lat": body.lat, "lng": body.lng, "timestamp": now},
            "updated_at": now,
        }},
    )

    # Publish to WebSocket channel for real-time tracking
    await publish(
        f"location:{user_id}",
        json.dumps({
            "event": "location_update",
            "user_id": user_id,
            "lat": body.lat,
            "lng": body.lng,
            "speed": body.speed,
            "heading": body.heading,
            "timestamp": now.isoformat(),
        }),
    )

    return {"success": True, "message": "Location updated"}


# ── Get current location ──────────────────────────────────────────────────────

@router.get("/current")
async def get_current_location(current_user: dict = Depends(get_current_user)):
    last = current_user.get("last_location")
    if not last:
        raise HTTPException(status_code=404, detail="No location data found")
    return {"success": True, "data": serialize_doc(last)}


# ── Location history ──────────────────────────────────────────────────────────

@router.get("/history")
async def location_history(
    limit: int = Query(default=100, le=500),
    session_id: str | None = None,
    current_user: dict = Depends(get_current_user),
):
    col = get_collection("locations")
    query: dict = {"user_id": str(current_user["_id"])}
    if session_id:
        query["session_id"] = session_id

    cursor = col.find(query).sort("timestamp", -1).limit(limit)
    items = [serialize_doc(loc) for loc in await cursor.to_list(length=limit)]
    return {"success": True, "data": items, "count": len(items)}


@router.delete("/history")
async def clear_location_history(current_user: dict = Depends(get_current_user)):
    col = get_collection("locations")
    result = await col.delete_many({"user_id": str(current_user["_id"])})
    return {"success": True, "message": f"Deleted {result.deleted_count} location records"}


# ── Nearby safe places ────────────────────────────────────────────────────────

@router.get("/nearby")
async def nearby_safe_places(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    radius_km: float = Query(default=5.0, ge=0.1, le=50.0),
    place_type: str = Query(default="all"),
    current_user: dict = Depends(get_current_user),
):
    results = []
    for place in SAFE_PLACES_DB:
        if place_type != "all" and place["type"] != place_type:
            continue
        dist = haversine_km(lat, lng, place["lat"], place["lng"])
        if dist <= radius_km:
            results.append({
                **place,
                "distance_km": round(dist, 2),
                "eta_minutes": round(dist / 5 * 60),  # walking ~5km/h
            })

    results.sort(key=lambda x: x["distance_km"])
    logger.info("Nearby search: user=%s found %d places", current_user["_id"], len(results))
    return {"success": True, "data": results, "count": len(results)}


# ── Share location link ───────────────────────────────────────────────────────

@router.post("/share")
async def create_share_link(current_user: dict = Depends(get_current_user)):
    import uuid
    token = uuid.uuid4().hex[:16]
    r_key = f"share_loc:{token}"

    from app.database.redis_client import get_redis
    r = get_redis()
    await r.setex(r_key, 3600 * 12, str(current_user["_id"]))  # 12h TTL

    return {
        "success": True,
        "data": {
            "share_url": f"https://safeher.app/live/{token}",
            "token": token,
            "expires_in_hours": 12,
        },
    }


@router.get("/share/{token}")
async def get_shared_location(token: str):
    from app.database.redis_client import get_redis
    r = get_redis()
    user_id = await r.get(f"share_loc:{token}")
    if not user_id:
        raise HTTPException(status_code=404, detail="Share link not found or expired")

    users = get_collection("users")
    user = await users.find_one({"_id": user_id}, {"full_name": 1, "last_location": 1})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return {
        "success": True,
        "data": {
            "user_name": user.get("full_name"),
            "last_location": serialize_doc(user.get("last_location")),
        },
    }
