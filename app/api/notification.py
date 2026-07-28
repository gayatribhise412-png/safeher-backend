"""
Notification API — in-app notifications + FCM push.
"""
import logging
from fastapi import APIRouter, Depends, Query
from app.schemas.sos import NotificationReadRequest
from app.database.mongodb import get_collection
from app.utils.dependencies import get_current_user
from app.utils.helpers import utcnow, serialize_doc

logger = logging.getLogger("safeher.notification")
router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.get("")
async def list_notifications(
    unread_only: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, le=100),
    current_user: dict = Depends(get_current_user),
):
    col = get_collection("notifications")
    query: dict = {"user_id": str(current_user["_id"])}
    if unread_only:
        query["is_read"] = False

    skip = (page - 1) * limit
    cursor = col.find(query).sort("created_at", -1).skip(skip).limit(limit)
    items = [serialize_doc(n) for n in await cursor.to_list(length=limit)]
    total = await col.count_documents(query)
    unread_count = await col.count_documents({"user_id": str(current_user["_id"]), "is_read": False})

    return {
        "success": True,
        "data": items,
        "pagination": {"page": page, "limit": limit, "total": total},
        "unread_count": unread_count,
    }


@router.post("/mark-read")
async def mark_read(
    body: NotificationReadRequest,
    current_user: dict = Depends(get_current_user),
):
    col = get_collection("notifications")
    result = await col.update_many(
        {"_id": {"$in": body.notification_ids}, "user_id": str(current_user["_id"])},
        {"$set": {"is_read": True, "read_at": utcnow()}},
    )
    return {"success": True, "message": f"{result.modified_count} notifications marked as read"}


@router.delete("")
async def delete_notifications(
    ids: list[str] = Query(...),
    current_user: dict = Depends(get_current_user),
):
    col = get_collection("notifications")
    result = await col.delete_many({"_id": {"$in": ids}, "user_id": str(current_user["_id"])})
    return {"success": True, "message": f"{result.deleted_count} notifications deleted"}


@router.delete("/all")
async def clear_all_notifications(current_user: dict = Depends(get_current_user)):
    col = get_collection("notifications")
    result = await col.delete_many({"user_id": str(current_user["_id"])})
    return {"success": True, "message": f"All {result.deleted_count} notifications cleared"}
