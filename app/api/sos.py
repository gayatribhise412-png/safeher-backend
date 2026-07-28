"""
SOS alert API — trigger, update, resolve, history.
On trigger: notifies contacts via SMS/call/email (background tasks),
broadcasts over WebSocket, and stores full audit trail.
"""
import uuid
import logging
from fastapi import APIRouter, HTTPException, status, Depends, BackgroundTasks

from bson import ObjectId

from app.schemas.sos import SOSCreateRequest, SOSUpdateRequest, SOSResponse
from app.models.sos import SOSStatus, SOSTriggerType
from app.database.mongodb import get_collection
from app.database.redis_client import get_redis, publish
from app.utils.dependencies import get_current_user
from app.utils.helpers import utcnow, serialize_doc, build_geo_point
from app.config import settings

import json

logger = logging.getLogger("safeher.sos")
router = APIRouter(prefix="/sos", tags=["SOS Emergency"])


async def _notify_contacts_task(user_id: str, sos_id: str, user_name: str, location: dict | None):
    """Background: fetch contacts and dispatch all notifications."""
    try:
        from app.services.sms_service import SMSService
        from app.services.twilio_service import TwilioService

        contacts_col = get_collection("emergency_contacts")
        cursor = contacts_col.find({"user_id": user_id, "is_trusted": True}).sort("priority", 1)
        contacts = await cursor.to_list(length=10)

        location_str = ""
        if location:
            lat, lng = location.get("lat"), location.get("lng")
            location_str = f"\nLocation: https://maps.google.com/?q={lat},{lng}"

        tracking_url = f"{settings.APP_NAME}/track/{sos_id}"
        message = (
            f"🆘 EMERGENCY ALERT from {user_name}!\n"
            f"She has activated the SafeHer SOS button and may need immediate help.\n"
            f"Live tracking: {tracking_url}{location_str}\n"
            f"Please call her or go to her location immediately."
        )

        notified_records = []
        for contact in contacts:
            record = {
                "contact_id": str(contact["_id"]),
                "contact_name": contact["name"],
                "phone": contact["phone"],
                "sms_sent": False,
                "call_made": False,
                "email_sent": False,
                "whatsapp_sent": False,
            }

            # SMS
            if contact.get("notify_via_sms", True):
                try:
                    await SMSService.send_sms(contact["phone"], message)
                    record["sms_sent"] = True
                    logger.info("SOS SMS sent to %s", contact["phone"])
                except Exception as e:
                    logger.error("SMS failed for %s: %s", contact["phone"], e)

            # Voice call
            if contact.get("notify_via_call", False):
                try:
                    await TwilioService.make_sos_call(contact["phone"], user_name, tracking_url)
                    record["call_made"] = True
                except Exception as e:
                    logger.error("Call failed for %s: %s", contact["phone"], e)

            notified_records.append(record)

            # Update last_notified
            await contacts_col.update_one(
                {"_id": contact["_id"]},
                {"$set": {"last_notified": utcnow()}, "$inc": {"notification_count": 1}},
            )

        # Update SOS doc with notification records
        sos_col = get_collection("sos_alerts")
        await sos_col.update_one(
            {"_id": sos_id},
            {"$set": {
                "notifications": notified_records,
                "contacts_notified": len(notified_records),
                "updated_at": utcnow(),
            }},
        )
        logger.info("SOS %s — notified %d contacts", sos_id, len(notified_records))

    except Exception as exc:
        logger.exception("Error in SOS notification task: %s", exc)


# ── Trigger SOS ───────────────────────────────────────────────────────────────

@router.post("", response_model=dict, status_code=status.HTTP_201_CREATED)
async def trigger_sos(
    body: SOSCreateRequest,
    background: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
):
    user_id = str(current_user["_id"])
    sos_id = str(ObjectId())
    now = utcnow()
    tracking_token = uuid.uuid4().hex[:12]

    location_doc = None
    if body.location:
        location_doc = body.location.model_dump()
        location_doc["timestamp"] = now
        location_doc["geo"] = build_geo_point(body.location.lat, body.location.lng)

    sos_doc = {
        "_id": sos_id,
        "user_id": user_id,
        "user_name": current_user.get("full_name", "Unknown"),
        "user_phone": current_user.get("phone"),
        "trigger_type": body.trigger_type,
        "status": SOSStatus.ACTIVE,
        "location": location_doc,
        "location_history": [location_doc] if location_doc else [],
        "message": body.message,
        "audio_file_url": body.audio_file_url,
        "ml_confidence": body.ml_confidence,
        "tracking_token": tracking_token,
        "tracking_url": f"https://safeher.app/track/{tracking_token}",
        "notifications": [],
        "contacts_notified": 0,
        "created_at": now,
        "updated_at": now,
    }

    sos_col = get_collection("sos_alerts")
    await sos_col.insert_one(sos_doc)

    # Store active SOS in Redis for fast WebSocket broadcast
    r = get_redis()
    await r.setex(f"active_sos:{user_id}", 7200, sos_id)  # 2h TTL

    # Publish to WebSocket channel
    await publish(
        f"sos:{user_id}",
        json.dumps({"event": "sos_triggered", "sos_id": sos_id, "user_id": user_id}),
    )

    # Background: notify contacts
    background.add_task(
        _notify_contacts_task,
        user_id,
        sos_id,
        current_user.get("full_name", "Unknown"),
        location_doc,
    )

    logger.warning("🆘 SOS TRIGGERED — user=%s id=%s trigger=%s", user_id, sos_id, body.trigger_type)

    return {
        "success": True,
        "message": "SOS activated. Emergency contacts are being notified.",
        "data": {
            "sos_id": sos_id,
            "tracking_url": sos_doc["tracking_url"],
            "tracking_token": tracking_token,
        },
    }


# ── Get active SOS ────────────────────────────────────────────────────────────

@router.get("/active")
async def get_active_sos(current_user: dict = Depends(get_current_user)):
    sos_col = get_collection("sos_alerts")
    sos = await sos_col.find_one(
        {"user_id": str(current_user["_id"]), "status": SOSStatus.ACTIVE},
        sort=[("created_at", -1)],
    )
    if not sos:
        return {"success": True, "data": None}
    return {"success": True, "data": serialize_doc(sos)}


# ── Cancel / resolve SOS ──────────────────────────────────────────────────────

@router.patch("/{sos_id}", response_model=dict)
async def update_sos(
    sos_id: str,
    body: SOSUpdateRequest,
    background: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
):
    sos_col = get_collection("sos_alerts")
    sos = await sos_col.find_one({"_id": sos_id, "user_id": str(current_user["_id"])})
    if not sos:
        raise HTTPException(status_code=404, detail="SOS alert not found")

    updates: dict = {"updated_at": utcnow()}
    if body.status:
        updates["status"] = body.status
        if body.status in (SOSStatus.RESOLVED, SOSStatus.CANCELLED):
            updates["resolved_at"] = utcnow()
            updates["resolved_by"] = "user"
            # Clear active SOS from Redis
            r = get_redis()
            await r.delete(f"active_sos:{current_user['_id']}")
    if body.resolution_notes:
        updates["resolution_notes"] = body.resolution_notes
    if body.location:
        loc = body.location.model_dump()
        loc["timestamp"] = utcnow()
        updates["location"] = loc
        # Append to history
        await sos_col.update_one({"_id": sos_id}, {"$push": {"location_history": loc}})

    await sos_col.update_one({"_id": sos_id}, {"$set": updates})

    # Broadcast resolution
    await publish(
        f"sos:{current_user['_id']}",
        json.dumps({"event": "sos_updated", "sos_id": sos_id, "status": body.status}),
    )

    updated = await sos_col.find_one({"_id": sos_id})
    return {"success": True, "data": serialize_doc(updated)}


# ── SOS history ───────────────────────────────────────────────────────────────

@router.get("/history")
async def sos_history(
    page: int = 1,
    limit: int = 20,
    current_user: dict = Depends(get_current_user),
):
    sos_col = get_collection("sos_alerts")
    skip = (page - 1) * limit
    cursor = sos_col.find({"user_id": str(current_user["_id"])}).sort("created_at", -1).skip(skip).limit(limit)
    items = [serialize_doc(s) for s in await cursor.to_list(length=limit)]
    total = await sos_col.count_documents({"user_id": str(current_user["_id"])})
    return {"success": True, "data": items, "total": total, "page": page, "limit": limit}


# ── Public tracking endpoint (no auth — uses token) ───────────────────────────

@router.get("/track/{token}")
async def get_sos_by_token(token: str):
    sos_col = get_collection("sos_alerts")
    sos = await sos_col.find_one({"tracking_token": token})
    if not sos:
        raise HTTPException(status_code=404, detail="Tracking link not found or expired")
    # Return limited public info
    return {
        "success": True,
        "data": {
            "user_name": sos.get("user_name"),
            "status": sos.get("status"),
            "location": sos.get("location"),
            "created_at": serialize_doc(sos.get("created_at")),
        },
    }
