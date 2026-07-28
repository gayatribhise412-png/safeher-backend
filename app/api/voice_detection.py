"""
Voice/audio detection API.
Accepts an audio upload, runs ML analysis, and optionally triggers SOS.
"""
import logging
import os
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, BackgroundTasks
from bson import ObjectId

from app.utils.dependencies import get_current_user
from app.utils.helpers import utcnow
from app.database.mongodb import get_collection
from app.ml.scream_detection import ScreamDetector
from app.ml.distress_detection import DistressDetector
from app.config import settings

logger = logging.getLogger("safeher.voice")
router = APIRouter(prefix="/voice", tags=["Voice Detection"])

ALLOWED_AUDIO_TYPES = {"audio/wav", "audio/mpeg", "audio/webm", "audio/ogg", "audio/mp4"}
MAX_AUDIO_SIZE_MB = 10


@router.post("/analyze")
async def analyze_audio(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    lat: float | None = None,
    lng: float | None = None,
    current_user: dict = Depends(get_current_user),
):
    # Validate
    if file.content_type not in ALLOWED_AUDIO_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported audio format: {file.content_type}")

    audio_bytes = await file.read()
    size_mb = len(audio_bytes) / (1024 * 1024)
    if size_mb > MAX_AUDIO_SIZE_MB:
        raise HTTPException(status_code=413, detail=f"Audio file too large. Max {MAX_AUDIO_SIZE_MB}MB")

    # Run ML analysis
    scream_result = await ScreamDetector.analyze(audio_bytes)
    distress_result = await DistressDetector.analyze(audio_bytes)

    is_distress = distress_result["is_distress"]
    is_scream = scream_result["is_scream"]
    confidence = max(scream_result["confidence"], distress_result["confidence"])
    emotion = distress_result.get("emotion")
    auto_sos = False

    # Auto-SOS if confidence above threshold and setting enabled
    settings_doc = current_user.get("settings", {})
    if (is_scream or is_distress) and confidence >= settings.SCREAM_DETECTION_THRESHOLD:
        if settings_doc.get("auto_share_location", True):
            auto_sos = True
            background.add_task(_auto_trigger_sos, str(current_user["_id"]), lat, lng, confidence)
            logger.warning("🎙️ Auto-SOS via voice: user=%s conf=%.2f", current_user["_id"], confidence)

    # Store recording metadata
    rec_col = get_collection("voice_recordings")
    await rec_col.insert_one({
        "_id": str(ObjectId()),
        "user_id": str(current_user["_id"]),
        "filename": file.filename,
        "content_type": file.content_type,
        "size_bytes": len(audio_bytes),
        "is_scream": is_scream,
        "is_distress": is_distress,
        "confidence": confidence,
        "emotion": emotion,
        "auto_sos_triggered": auto_sos,
        "lat": lat,
        "lng": lng,
        "created_at": utcnow(),
    })

    recommendation = (
        "SOS has been automatically triggered." if auto_sos
        else "Elevated distress detected. Consider activating SOS manually." if is_distress or is_scream
        else "No distress detected. You appear safe."
    )

    return {
        "success": True,
        "data": {
            "is_distress": is_distress,
            "is_scream": is_scream,
            "confidence": round(confidence, 3),
            "emotion": emotion,
            "recommendation": recommendation,
            "auto_sos_triggered": auto_sos,
        },
    }


@router.get("/recordings")
async def list_recordings(current_user: dict = Depends(get_current_user)):
    col = get_collection("voice_recordings")
    cursor = col.find({"user_id": str(current_user["_id"])}).sort("created_at", -1).limit(50)
    from app.utils.helpers import serialize_doc
    items = [serialize_doc(r) for r in await cursor.to_list(length=50)]
    return {"success": True, "data": items}


async def _auto_trigger_sos(user_id: str, lat: float | None, lng: float | None, confidence: float):
    """Background: trigger an AI-detected SOS alert."""
    from app.models.sos import SOSTriggerType, SOSStatus
    from app.database.mongodb import get_collection as gc
    from app.utils.helpers import build_geo_point
    import uuid

    sos_col = gc("sos_alerts")
    users_col = gc("users")
    user = await users_col.find_one({"_id": user_id})
    if not user:
        return

    sos_id = str(ObjectId())
    now = utcnow()
    tracking_token = uuid.uuid4().hex[:12]

    location_doc = None
    if lat and lng:
        location_doc = {"lat": lat, "lng": lng, "timestamp": now, "geo": build_geo_point(lat, lng)}

    await sos_col.insert_one({
        "_id": sos_id,
        "user_id": user_id,
        "user_name": user.get("full_name", "Unknown"),
        "user_phone": user.get("phone"),
        "trigger_type": SOSTriggerType.VOICE,
        "status": SOSStatus.ACTIVE,
        "location": location_doc,
        "location_history": [location_doc] if location_doc else [],
        "ml_confidence": confidence,
        "ml_model": "scream_detector",
        "tracking_token": tracking_token,
        "tracking_url": f"https://safeher.app/track/{tracking_token}",
        "notifications": [],
        "contacts_notified": 0,
        "created_at": now,
        "updated_at": now,
    })

    from app.api.sos import _notify_contacts_task
    await _notify_contacts_task(user_id, sos_id, user.get("full_name", "Unknown"), location_doc)
