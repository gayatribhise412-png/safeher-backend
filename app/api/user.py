"""
User profile and emergency contacts management.
"""
import logging
from fastapi import APIRouter, HTTPException, status, Depends, UploadFile, File

from app.schemas.user import (
    UserUpdateRequest, UpdateSettingsRequest, FCMTokenRequest,
    UserResponse, ContactCreateRequest, ContactUpdateRequest, ContactResponse,
)
from app.database.mongodb import get_collection
from app.utils.dependencies import get_current_user
from app.utils.helpers import utcnow, serialize_doc
from bson import ObjectId

logger = logging.getLogger("safeher.user")
router = APIRouter(prefix="/users", tags=["Users"])


def _safe_user(doc: dict) -> dict:
    """Strip sensitive fields and normalise _id."""
    doc = dict(doc)
    doc.pop("password_hash", None)
    doc.pop("fcm_tokens", None)
    if "_id" in doc:
        doc["id"] = str(doc.pop("_id"))
    return serialize_doc(doc)


# ── Profile ───────────────────────────────────────────────────────────────────

@router.get("/me")
async def get_profile(current_user: dict = Depends(get_current_user)):
    return {"success": True, "data": _safe_user(current_user)}


@router.put("/me")
async def update_profile(
    body: UserUpdateRequest,
    current_user: dict = Depends(get_current_user),
):
    users = get_collection("users")
    updates = {k: v for k, v in body.model_dump(exclude_none=True).items()}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    updates["updated_at"] = utcnow()
    await users.update_one({"_id": current_user["_id"]}, {"$set": updates})
    updated = await users.find_one({"_id": current_user["_id"]})
    return {"success": True, "data": _safe_user(updated)}


@router.delete("/me", status_code=status.HTTP_200_OK)
async def deactivate_account(current_user: dict = Depends(get_current_user)):
    """Soft-delete — sets is_active=False."""
    users = get_collection("users")
    await users.update_one(
        {"_id": current_user["_id"]},
        {"$set": {"is_active": False, "updated_at": utcnow()}},
    )
    logger.info("Account deactivated: %s", current_user["email"])
    return {"success": True, "message": "Account deactivated"}


# ── Settings ──────────────────────────────────────────────────────────────────

@router.put("/me/settings")
async def update_settings(
    body: UpdateSettingsRequest,
    current_user: dict = Depends(get_current_user),
):
    updates = {k: v for k, v in body.model_dump(exclude_none=True).items()}
    if not updates:
        raise HTTPException(status_code=400, detail="No settings provided")

    users = get_collection("users")
    # Merge into existing settings sub-document
    set_fields = {f"settings.{k}": v for k, v in updates.items()}
    set_fields["updated_at"] = utcnow()
    await users.update_one({"_id": current_user["_id"]}, {"$set": set_fields})
    updated = await users.find_one({"_id": current_user["_id"]})
    return {"success": True, "data": {"settings": updated.get("settings", {})}}


# ── FCM token (push notifications) ───────────────────────────────────────────

@router.post("/me/fcm-token")
async def register_fcm_token(
    body: FCMTokenRequest,
    current_user: dict = Depends(get_current_user),
):
    users = get_collection("users")
    existing: list = current_user.get("fcm_tokens", [])
    if body.fcm_token not in existing:
        existing.append(body.fcm_token)
    await users.update_one(
        {"_id": current_user["_id"]},
        {"$set": {"fcm_tokens": existing[-5:], "updated_at": utcnow()}},
    )
    return {"success": True, "message": "FCM token registered"}


@router.delete("/me/fcm-token")
async def remove_fcm_token(
    body: FCMTokenRequest,
    current_user: dict = Depends(get_current_user),
):
    users = get_collection("users")
    existing: list = current_user.get("fcm_tokens", [])
    updated_tokens = [t for t in existing if t != body.fcm_token]
    await users.update_one(
        {"_id": current_user["_id"]},
        {"$set": {"fcm_tokens": updated_tokens, "updated_at": utcnow()}},
    )
    return {"success": True, "message": "FCM token removed"}


# ── Safety score ──────────────────────────────────────────────────────────────

@router.get("/me/safety-score")
async def get_safety_score(current_user: dict = Depends(get_current_user)):
    """Compute real-time safety score based on profile completeness and activity."""
    score = 40  # base
    if current_user.get("phone_verified"):
        score += 10
    if current_user.get("email_verified"):
        score += 10
    contacts_col = get_collection("emergency_contacts")
    contact_count = await contacts_col.count_documents({"user_id": str(current_user["_id"])})
    score += min(contact_count * 10, 30)  # up to 30 pts for contacts
    if current_user.get("settings", {}).get("auto_share_location"):
        score += 10
    score = min(score, 100)

    # Persist updated score
    users = get_collection("users")
    await users.update_one({"_id": current_user["_id"]}, {"$set": {"safety_score": score}})

    return {"success": True, "data": {"safety_score": score, "breakdown": {
        "base": 40,
        "phone_verified": 10 if current_user.get("phone_verified") else 0,
        "email_verified": 10 if current_user.get("email_verified") else 0,
        "contacts": min(contact_count * 10, 30),
        "auto_location": 10 if current_user.get("settings", {}).get("auto_share_location") else 0,
    }}}


# ── Emergency contacts ────────────────────────────────────────────────────────

@router.get("/me/contacts")
async def list_contacts(current_user: dict = Depends(get_current_user)):
    col = get_collection("emergency_contacts")
    cursor = col.find({"user_id": str(current_user["_id"])}).sort("priority", 1)
    contacts = [serialize_doc(c) for c in await cursor.to_list(length=20)]
    for c in contacts:
        if "_id" in c:
            c["id"] = str(c.pop("_id"))
    return {"success": True, "data": contacts}


@router.post("/me/contacts", status_code=status.HTTP_201_CREATED)
async def add_contact(
    body: ContactCreateRequest,
    current_user: dict = Depends(get_current_user),
):
    col = get_collection("emergency_contacts")
    count = await col.count_documents({"user_id": str(current_user["_id"])})
    if count >= 10:
        raise HTTPException(status_code=400, detail="Maximum 10 emergency contacts allowed")

    # Check duplicate phone
    existing = await col.find_one({"user_id": str(current_user["_id"]), "phone": body.phone})
    if existing:
        raise HTTPException(status_code=409, detail="This phone number is already in your contacts")

    now = utcnow()
    doc = {
        "_id": str(ObjectId()),
        "user_id": str(current_user["_id"]),
        **body.model_dump(),
        "created_at": now,
        "updated_at": now,
        "last_notified": None,
        "notification_count": 0,
    }
    await col.insert_one(doc)

    # Update count on user
    users = get_collection("users")
    await users.update_one(
        {"_id": current_user["_id"]},
        {"$inc": {"sos_contacts_count": 1}, "$set": {"updated_at": now}},
    )
    return {"success": True, "data": serialize_doc({**doc, "id": doc["_id"]})}


@router.put("/me/contacts/{contact_id}")
async def update_contact(
    contact_id: str,
    body: ContactUpdateRequest,
    current_user: dict = Depends(get_current_user),
):
    col = get_collection("emergency_contacts")
    contact = await col.find_one({"_id": contact_id, "user_id": str(current_user["_id"])})
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")

    updates = {k: v for k, v in body.model_dump(exclude_none=True).items()}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    updates["updated_at"] = utcnow()
    await col.update_one({"_id": contact_id}, {"$set": updates})
    updated = await col.find_one({"_id": contact_id})
    return {"success": True, "data": serialize_doc(updated)}


@router.delete("/me/contacts/{contact_id}", status_code=status.HTTP_200_OK)
async def delete_contact(
    contact_id: str,
    current_user: dict = Depends(get_current_user),
):
    col = get_collection("emergency_contacts")
    result = await col.delete_one({"_id": contact_id, "user_id": str(current_user["_id"])})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Contact not found")

    users = get_collection("users")
    await users.update_one(
        {"_id": current_user["_id"]},
        {"$inc": {"sos_contacts_count": -1}, "$set": {"updated_at": utcnow()}},
    )
    return {"success": True, "message": "Contact deleted"}
