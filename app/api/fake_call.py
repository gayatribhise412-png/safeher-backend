"""
Fake call API — schedule and trigger fake call alerts.
Uses WebSocket or push notification to trigger client-side call UI.
"""
import logging
import uuid
from fastapi import APIRouter, Depends, BackgroundTasks
from app.schemas.sos import FakeCallRequest
from app.database.redis_client import get_redis
from app.utils.dependencies import get_current_user

logger = logging.getLogger("safeher.fake_call")
router = APIRouter(prefix="/fake-call", tags=["Fake Call"])


@router.post("/trigger")
async def trigger_fake_call(
    body: FakeCallRequest,
    background: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
):
    user_id = str(current_user["_id"])
    call_id = uuid.uuid4().hex[:12]

    # Store call metadata in Redis for retrieval by client
    r = get_redis()
    await r.setex(
        f"fake_call:{call_id}",
        300,  # 5min TTL
        f"{body.caller_name}|{body.caller_number}|{user_id}",
    )

    # If delay > 0, schedule; else, send push immediately
    if body.delay_seconds > 0:
        # TODO: Use Celery/Redis queue for delayed tasks
        logger.info("Fake call scheduled: user=%s delay=%ds", user_id, body.delay_seconds)
    else:
        # TODO: Send push notification to trigger UI
        logger.info("Fake call triggered instantly: user=%s", user_id)

    return {
        "success": True,
        "message": f"Fake call {'scheduled' if body.delay_seconds > 0 else 'triggered'}",
        "data": {
            "call_id": call_id,
            "caller_name": body.caller_name,
            "caller_number": body.caller_number,
            "delay_seconds": body.delay_seconds,
        },
    }


@router.get("/status/{call_id}")
async def get_fake_call_status(call_id: str, current_user: dict = Depends(get_current_user)):
    r = get_redis()
    data = await r.get(f"fake_call:{call_id}")
    if not data:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Call not found or expired")

    caller_name, caller_number, user_id = data.split("|")
    return {
        "success": True,
        "data": {
            "call_id": call_id,
            "caller_name": caller_name,
            "caller_number": caller_number,
            "status": "pending",
        },
    }
