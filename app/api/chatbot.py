"""
AI Chatbot API — Aria, the SafeHer safety assistant.
Uses OpenAI GPT with a safety-first system prompt.
Session messages stored in MongoDB with 30-day TTL.
"""
import uuid
import logging
from fastapi import APIRouter, Depends, HTTPException

from app.schemas.sos import ChatMessageRequest, ChatMessageResponse
from app.services.ai_chatbot import AIChatbotService
from app.database.mongodb import get_collection
from app.utils.dependencies import get_current_user
from app.utils.helpers import utcnow, serialize_doc
from bson import ObjectId

logger = logging.getLogger("safeher.chatbot")
router = APIRouter(prefix="/chatbot", tags=["AI Chatbot"])


@router.post("/message")
async def chat(
    body: ChatMessageRequest,
    current_user: dict = Depends(get_current_user),
):
    user_id = str(current_user["_id"])
    session_id = body.session_id or uuid.uuid4().hex

    # Load conversation history (last 10 messages for context)
    chat_col = get_collection("chat_sessions")
    history_docs = await chat_col.find(
        {"user_id": user_id, "session_id": session_id}
    ).sort("created_at", -1).limit(10).to_list(length=10)
    history_docs.reverse()

    history = [
        {"role": doc["role"], "content": doc["content"]}
        for doc in history_docs
    ]

    # Get AI response
    response_text, intent, safety_action = await AIChatbotService.get_response(
        user_message=body.message,
        history=history,
        user_name=current_user.get("full_name", "there"),
    )

    now = utcnow()

    # Persist user message
    await chat_col.insert_one({
        "_id": str(ObjectId()),
        "user_id": user_id,
        "session_id": session_id,
        "role": "user",
        "content": body.message,
        "created_at": now,
    })

    # Persist assistant response
    await chat_col.insert_one({
        "_id": str(ObjectId()),
        "user_id": user_id,
        "session_id": session_id,
        "role": "assistant",
        "content": response_text,
        "intent": intent,
        "safety_action": safety_action,
        "created_at": now,
    })

    # If AI detected an emergency, trigger SOS automatically
    if safety_action == "trigger_sos":
        logger.warning("AI detected SOS intent for user %s — action: %s", user_id, safety_action)

    return {
        "success": True,
        "data": {
            "session_id": session_id,
            "user_message": body.message,
            "ai_response": response_text,
            "timestamp": now.isoformat(),
            "intent": intent,
            "safety_action": safety_action,
        },
    }


@router.get("/sessions")
async def list_sessions(current_user: dict = Depends(get_current_user)):
    """List distinct chat sessions for the user."""
    chat_col = get_collection("chat_sessions")
    pipeline = [
        {"$match": {"user_id": str(current_user["_id"])}},
        {"$group": {
            "_id": "$session_id",
            "last_message": {"$last": "$content"},
            "last_at": {"$last": "$created_at"},
            "message_count": {"$sum": 1},
        }},
        {"$sort": {"last_at": -1}},
        {"$limit": 20},
    ]
    sessions = await chat_col.aggregate(pipeline).to_list(length=20)
    return {"success": True, "data": serialize_doc(sessions)}


@router.get("/sessions/{session_id}")
async def get_session_messages(
    session_id: str,
    current_user: dict = Depends(get_current_user),
):
    chat_col = get_collection("chat_sessions")
    messages = await chat_col.find(
        {"user_id": str(current_user["_id"]), "session_id": session_id}
    ).sort("created_at", 1).to_list(length=200)
    return {"success": True, "data": serialize_doc(messages)}


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    current_user: dict = Depends(get_current_user),
):
    chat_col = get_collection("chat_sessions")
    result = await chat_col.delete_many(
        {"user_id": str(current_user["_id"]), "session_id": session_id}
    )
    return {"success": True, "message": f"Deleted {result.deleted_count} messages"}
