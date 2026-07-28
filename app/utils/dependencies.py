"""
FastAPI dependency functions — injected via Depends().
"""
import logging
from fastapi import Depends, HTTPException, status, WebSocket
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.utils.security import decode_access_token
from app.database.mongodb import get_collection

logger = logging.getLogger("safeher.deps")
bearer = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
) -> dict:
    """Validate JWT and return user document from MongoDB."""
    token = credentials.credentials
    payload = await decode_access_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    users = get_collection("users")
    user = await users.find_one({"_id": user_id, "is_active": True})
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")

    return user


async def get_current_user_ws(websocket: WebSocket, token: str) -> dict:
    """WebSocket auth — token passed as query param."""
    payload = await decode_access_token(token)
    if not payload:
        await websocket.close(code=4001)
        raise HTTPException(status_code=401, detail="Unauthorized")

    users = get_collection("users")
    user = await users.find_one({"_id": payload.get("sub"), "is_active": True})
    if not user:
        await websocket.close(code=4001)
        raise HTTPException(status_code=401, detail="User not found")

    return user


async def require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return current_user
