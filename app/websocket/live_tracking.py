"""
WebSocket live tracking — real-time location broadcasting.

Architecture for 5000 concurrent users:
  • Each user connects to /ws/track?token=<JWT>
  • Location updates are published to Redis Pub/Sub channel "location:<user_id>"
  • Contacts watching a user subscribe to the same channel via /ws/watch/<user_id>?token=<JWT>
  • Redis fan-out ensures updates reach all connected watchers across multiple
    Uvicorn/Gunicorn worker processes (horizontal scale-ready)

Connection manager runs per-process. Redis pub/sub bridges across processes.
"""
import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, HTTPException

from app.database.redis_client import get_redis, subscribe, publish
from app.utils.security import decode_access_token
from app.database.mongodb import get_collection
from app.utils.helpers import utcnow, build_geo_point
from app.config import settings
from bson import ObjectId

logger = logging.getLogger("safeher.ws")
router = APIRouter(tags=["WebSocket"])


# ── In-process connection registry ───────────────────────────────────────────

class ConnectionManager:
    """
    Thread-safe, per-process WebSocket registry.
    Redis pub/sub handles cross-process fan-out.
    """

    def __init__(self):
        # user_id → set of active WebSocket connections (multiple tabs/devices)
        self._connections: dict[str, set[WebSocket]] = {}

    async def connect(self, user_id: str, ws: WebSocket):
        await ws.accept()
        if user_id not in self._connections:
            self._connections[user_id] = set()
        # Enforce per-user connection limit
        if len(self._connections[user_id]) >= settings.WS_MAX_CONNECTIONS_PER_USER:
            oldest = next(iter(self._connections[user_id]))
            await self.disconnect(user_id, oldest)
        self._connections[user_id].add(ws)
        logger.debug("WS connected: user=%s total_for_user=%d", user_id, len(self._connections[user_id]))

    async def disconnect(self, user_id: str, ws: WebSocket):
        conns = self._connections.get(user_id, set())
        conns.discard(ws)
        if not conns:
            self._connections.pop(user_id, None)
        try:
            await ws.close()
        except Exception:
            pass
        logger.debug("WS disconnected: user=%s remaining=%d", user_id, len(conns))

    async def send_to_user(self, user_id: str, payload: dict):
        conns = self._connections.get(user_id, set())
        dead = set()
        msg = json.dumps(payload)
        for ws in conns:
            try:
                await ws.send_text(msg)
            except Exception:
                dead.add(ws)
        for ws in dead:
            await self.disconnect(user_id, ws)

    def active_count(self) -> int:
        return sum(len(v) for v in self._connections.values())


manager = ConnectionManager()


# ── Auth helper ───────────────────────────────────────────────────────────────

async def _auth_websocket(websocket: WebSocket, token: str) -> Optional[dict]:
    payload = await decode_access_token(token)
    if not payload:
        await websocket.close(code=4001, reason="Unauthorized")
        return None
    users = get_collection("users")
    user = await users.find_one({"_id": payload["sub"], "is_active": True})
    if not user:
        await websocket.close(code=4001, reason="User not found")
        return None
    return user


# ── User's own tracking endpoint ─────────────────────────────────────────────

@router.websocket("/ws/track")
async def ws_track(websocket: WebSocket, token: str = Query(...)):
    """
    User broadcasts their own location.
    Client sends: {"lat": float, "lng": float, "accuracy": float, "session_id": str}
    Server sends: {"event": "ack", "timestamp": str} and SOS status updates.
    """
    user = await _auth_websocket(websocket, token)
    if not user:
        return

    user_id = str(user["_id"])
    await manager.connect(user_id, websocket)
    logger.info("Track WS opened: user=%s", user_id)

    # Subscribe to this user's SOS/system channel for server → client pushes
    redis_pubsub = await subscribe(f"sos:{user_id}")

    async def _redis_listener():
        """Forward Redis pub/sub messages to this WebSocket client."""
        async for message in redis_pubsub.listen():
            if message["type"] == "message":
                try:
                    data = json.loads(message["data"])
                    await websocket.send_text(json.dumps(data))
                except Exception:
                    pass

    redis_task = asyncio.create_task(_redis_listener())

    try:
        # Heartbeat + location receive loop
        while True:
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=settings.WS_HEARTBEAT_INTERVAL + 5)
            except asyncio.TimeoutError:
                # Client missed heartbeat — send ping
                await websocket.send_text(json.dumps({"event": "ping"}))
                continue

            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue

            event = data.get("event", "location_update")

            if event == "pong":
                continue

            if event == "location_update":
                lat = data.get("lat")
                lng = data.get("lng")
                if lat is None or lng is None:
                    continue

                now = utcnow()

                # Persist to MongoDB (async, TTL-indexed)
                loc_col = get_collection("locations")
                await loc_col.insert_one({
                    "_id": str(ObjectId()),
                    "user_id": user_id,
                    "lat": lat,
                    "lng": lng,
                    "accuracy": data.get("accuracy"),
                    "speed": data.get("speed"),
                    "heading": data.get("heading"),
                    "session_id": data.get("session_id"),
                    "coordinates": build_geo_point(lat, lng),
                    "timestamp": now,
                })

                # Update user's last location
                users_col = get_collection("users")
                await users_col.update_one(
                    {"_id": user_id},
                    {"$set": {"last_location": {"lat": lat, "lng": lng, "timestamp": now}}},
                )

                # Publish to Redis → all watchers on any worker process receive this
                await publish(
                    f"location:{user_id}",
                    json.dumps({
                        "event": "location_update",
                        "user_id": user_id,
                        "lat": lat,
                        "lng": lng,
                        "speed": data.get("speed"),
                        "heading": data.get("heading"),
                        "timestamp": now.isoformat(),
                    }),
                )

                # Ack back to sender
                await websocket.send_text(json.dumps({"event": "ack", "timestamp": now.isoformat()}))

    except WebSocketDisconnect:
        logger.info("Track WS closed: user=%s", user_id)
    except Exception as exc:
        logger.error("Track WS error: user=%s — %s", user_id, exc)
    finally:
        redis_task.cancel()
        await redis_pubsub.unsubscribe(f"sos:{user_id}")
        await manager.disconnect(user_id, websocket)


# ── Watcher endpoint (contact monitoring another user) ───────────────────────

@router.websocket("/ws/watch/{target_user_id}")
async def ws_watch(
    websocket: WebSocket,
    target_user_id: str,
    token: str = Query(...),
    share_token: Optional[str] = Query(default=None),
):
    """
    Emergency contact watches another user's live location.
    Authenticated either by JWT (trusted contact) or share_token (public link).
    Client receives: {"event": "location_update", "lat", "lng", "timestamp"} continuously.
    """
    # Auth: JWT or share token
    if token and token != "share":
        user = await _auth_websocket(websocket, token)
        if not user:
            return
        watcher_id = str(user["_id"])

        # Verify watcher is an emergency contact of target
        contacts_col = get_collection("emergency_contacts")
        is_contact = await contacts_col.find_one({
            "user_id": target_user_id,
            "phone": user.get("phone", ""),
        })
        if not is_contact:
            await websocket.close(code=4003, reason="Not authorised to watch this user")
            return
    elif share_token:
        # Validate share token from Redis
        r = get_redis()
        stored_uid = await r.get(f"share_loc:{share_token}")
        if not stored_uid or stored_uid != target_user_id:
            await websocket.close(code=4001, reason="Invalid share token")
            return
        watcher_id = "anonymous"
    else:
        await websocket.close(code=4001, reason="No auth provided")
        return

    await websocket.accept()
    logger.info("Watch WS opened: watcher=%s watching=%s", watcher_id, target_user_id)

    # Subscribe to target user's location channel
    pubsub = await subscribe(f"location:{target_user_id}")

    # Send last known location immediately on connect
    users_col = get_collection("users")
    target = await users_col.find_one({"_id": target_user_id}, {"last_location": 1, "full_name": 1})
    if target and target.get("last_location"):
        await websocket.send_text(json.dumps({
            "event": "initial_location",
            "user_name": target.get("full_name"),
            **{k: str(v) if hasattr(v, 'isoformat') else v for k, v in target["last_location"].items()},
        }))

    try:
        while True:
            # Receive from Redis pub/sub (blocking)
            msg_task = asyncio.create_task(_wait_for_pubsub(pubsub))
            ping_task = asyncio.create_task(asyncio.sleep(settings.WS_HEARTBEAT_INTERVAL))

            done, pending = await asyncio.wait(
                [msg_task, ping_task],
                return_when=asyncio.FIRST_COMPLETED,
            )

            for t in pending:
                t.cancel()

            if msg_task in done:
                message = msg_task.result()
                if message:
                    await websocket.send_text(message)
            else:
                # Heartbeat
                await websocket.send_text(json.dumps({"event": "ping"}))
                try:
                    pong = await asyncio.wait_for(websocket.receive_text(), timeout=10)
                except asyncio.TimeoutError:
                    logger.debug("Watch WS heartbeat timeout: watcher=%s", watcher_id)
                    break

    except WebSocketDisconnect:
        logger.info("Watch WS closed: watcher=%s", watcher_id)
    except Exception as exc:
        logger.error("Watch WS error: %s", exc)
    finally:
        await pubsub.unsubscribe(f"location:{target_user_id}")
        try:
            await websocket.close()
        except Exception:
            pass


async def _wait_for_pubsub(pubsub) -> Optional[str]:
    """Await next message from a Redis pub/sub subscription."""
    async for message in pubsub.listen():
        if message["type"] == "message":
            return message["data"]
    return None


# ── SOS alert broadcast endpoint ─────────────────────────────────────────────

@router.websocket("/ws/sos/{user_id}")
async def ws_sos_updates(
    websocket: WebSocket,
    user_id: str,
    token: str = Query(...),
):
    """
    Receive real-time SOS lifecycle events for a given user.
    Used by dashboard to show live SOS status.
    """
    user = await _auth_websocket(websocket, token)
    if not user:
        return

    if str(user["_id"]) != user_id and user.get("role") != "admin":
        await websocket.close(code=4003, reason="Forbidden")
        return

    await websocket.accept()
    pubsub = await subscribe(f"sos:{user_id}")
    logger.info("SOS WS opened: user=%s", user_id)

    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                await websocket.send_text(message["data"])
    except WebSocketDisconnect:
        logger.info("SOS WS closed: user=%s", user_id)
    finally:
        await pubsub.unsubscribe(f"sos:{user_id}")
        try:
            await websocket.close()
        except Exception:
            pass


# ── Stats endpoint (admin) ────────────────────────────────────────────────────

@router.get("/ws/stats")
async def ws_stats():
    """Return in-process WebSocket connection count (admin/monitoring)."""
    return {"active_connections": manager.active_count()}
