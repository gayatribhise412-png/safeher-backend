"""
Authentication API — register, login, logout, refresh, password management.
All passwords hashed with bcrypt. Tokens issued as JWT access + refresh pair.
"""
import uuid
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, status, Depends, BackgroundTasks, Request
from bson import ObjectId

from app.schemas.auth import (
    RegisterRequest, LoginRequest, RefreshRequest, TokenResponse,
    ChangePasswordRequest, ForgotPasswordRequest, ResetPasswordRequest, MessageResponse,
)
from app.database.mongodb import get_collection
from app.database.redis_client import blacklist_token, get_redis
from app.utils.security import (
    hash_password, verify_password,
    create_access_token, create_refresh_token, decode_access_token,
)
from app.utils.dependencies import get_current_user
from app.utils.helpers import utcnow, sha256, serialize_doc
from app.config import settings

logger = logging.getLogger("safeher.auth")
router = APIRouter(prefix="/auth", tags=["Authentication"])


# ── Register ──────────────────────────────────────────────────────────────────

@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, background: BackgroundTasks):
    users = get_collection("users")

    # Duplicate checks
    if await users.find_one({"email": body.email.lower()}):
        raise HTTPException(status_code=409, detail="Email already registered")
    if await users.find_one({"phone": body.phone}):
        raise HTTPException(status_code=409, detail="Phone number already registered")

    user_id = str(ObjectId())
    now = utcnow()

    user_doc = {
        "_id": user_id,
        "email": body.email.lower(),
        "phone": body.phone,
        "password_hash": hash_password(body.password),
        "full_name": body.full_name,
        "city": body.city,
        "state": body.state,
        "country": body.country,
        "role": "user",
        "safety_score": 85,
        "is_active": True,
        "is_verified": False,
        "is_premium": False,
        "email_verified": False,
        "phone_verified": False,
        "sos_contacts_count": 0,
        "fcm_tokens": [],
        "settings": {
            "sos_sound": True,
            "sos_vibration": True,
            "auto_share_location": True,
            "push_notifications": True,
            "email_notifications": False,
            "sms_notifications": True,
            "dark_mode": True,
            "language": "en",
            "location_history_enabled": True,
            "biometric_enabled": False,
        },
        "created_at": now,
        "updated_at": now,
        "last_login": now,
    }

    await users.insert_one(user_doc)
    logger.info("New user registered: %s (id=%s)", body.email, user_id)

    access_token, _ = create_access_token(user_id, body.email.lower())
    refresh_token, refresh_jti = create_refresh_token(user_id)

    # Persist refresh token hash
    rt_col = get_collection("refresh_tokens")
    await rt_col.insert_one({
        "_id": str(ObjectId()),
        "user_id": user_id,
        "token_hash": sha256(refresh_token),
        "jti": refresh_jti,
        "created_at": now,
        "expires_at": now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    })

    safe_user = {k: v for k, v in user_doc.items() if k not in ("password_hash",)}
    serialize_doc(safe_user)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=serialize_doc(safe_user),
    )


# ── Login ─────────────────────────────────────────────────────────────────────

@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, request: Request):
    users = get_collection("users")
    user = await users.find_one({"email": body.email.lower()})

    if not user or not verify_password(body.password, user.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not user.get("is_active", True):
        raise HTTPException(status_code=403, detail="Account disabled. Contact support.")

    now = utcnow()
    update_fields: dict = {"last_login": now, "updated_at": now}

    # Persist FCM token if provided
    if body.fcm_token:
        # Deduplicate — keep max 5 tokens per user
        existing: list = user.get("fcm_tokens", [])
        if body.fcm_token not in existing:
            existing.append(body.fcm_token)
        update_fields["fcm_tokens"] = existing[-5:]

    if body.device_info:
        update_fields["device_info"] = body.device_info

    await users.update_one({"_id": user["_id"]}, {"$set": update_fields})

    user_id = str(user["_id"])
    access_token, _ = create_access_token(user_id, user["email"], user.get("role", "user"))
    refresh_token, refresh_jti = create_refresh_token(user_id)

    rt_col = get_collection("refresh_tokens")
    await rt_col.insert_one({
        "_id": str(ObjectId()),
        "user_id": user_id,
        "token_hash": sha256(refresh_token),
        "jti": refresh_jti,
        "created_at": now,
        "expires_at": now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    })

    safe_user = {k: v for k, v in user.items() if k not in ("password_hash",)}
    logger.info("User logged in: %s", user["email"])

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=serialize_doc(safe_user),
    )


# ── Refresh ───────────────────────────────────────────────────────────────────

@router.post("/refresh", response_model=TokenResponse)
async def refresh_token_endpoint(body: RefreshRequest):
    payload = await decode_access_token(body.refresh_token)
    # Refresh tokens have type="refresh" — re-decode without type check
    from jose import jwt as _jwt
    try:
        payload = _jwt.decode(
            body.refresh_token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Not a refresh token")

    token_hash = sha256(body.refresh_token)
    rt_col = get_collection("refresh_tokens")
    rt_doc = await rt_col.find_one({"token_hash": token_hash})
    if not rt_doc:
        raise HTTPException(status_code=401, detail="Refresh token revoked or not found")

    # Rotate: delete old, issue new
    await rt_col.delete_one({"_id": rt_doc["_id"]})

    user_id = payload["sub"]
    users = get_collection("users")
    user = await users.find_one({"_id": user_id, "is_active": True})
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    now = utcnow()
    access_token, _ = create_access_token(user_id, user["email"], user.get("role", "user"))
    new_refresh, new_jti = create_refresh_token(user_id)

    await rt_col.insert_one({
        "_id": str(ObjectId()),
        "user_id": user_id,
        "token_hash": sha256(new_refresh),
        "jti": new_jti,
        "created_at": now,
        "expires_at": now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    })

    safe_user = {k: v for k, v in user.items() if k not in ("password_hash",)}
    return TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=serialize_doc(safe_user),
    )


# ── Logout ────────────────────────────────────────────────────────────────────

@router.post("/logout", response_model=MessageResponse)
async def logout(
    body: RefreshRequest,
    current_user: dict = Depends(get_current_user),
):
    # Revoke refresh token
    token_hash = sha256(body.refresh_token)
    rt_col = get_collection("refresh_tokens")
    await rt_col.delete_one({"token_hash": token_hash, "user_id": str(current_user["_id"])})
    logger.info("User logged out: %s", current_user["email"])
    return MessageResponse(success=True, message="Logged out successfully")


# ── Change password ───────────────────────────────────────────────────────────

@router.post("/change-password", response_model=MessageResponse)
async def change_password(
    body: ChangePasswordRequest,
    current_user: dict = Depends(get_current_user),
):
    if not verify_password(body.current_password, current_user.get("password_hash", "")):
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    users = get_collection("users")
    await users.update_one(
        {"_id": current_user["_id"]},
        {"$set": {"password_hash": hash_password(body.new_password), "updated_at": utcnow()}},
    )
    logger.info("Password changed for user: %s", current_user["email"])
    return MessageResponse(success=True, message="Password updated successfully")


# ── Forgot password ───────────────────────────────────────────────────────────

@router.post("/forgot-password", response_model=MessageResponse)
async def forgot_password(body: ForgotPasswordRequest, background: BackgroundTasks):
    users = get_collection("users")
    user = await users.find_one({"email": body.email.lower()})
    # Always return success to prevent user enumeration
    if user:
        reset_token = str(uuid.uuid4())
        r = get_redis()
        await r.setex(f"pwd_reset:{sha256(reset_token)}", 3600, str(user["_id"]))
        # TODO: background.add_task(email_service.send_password_reset, user["email"], reset_token)
        logger.info("Password reset requested for: %s", body.email)
    return MessageResponse(success=True, message="If that email exists, a reset link has been sent")


# ── Reset password ────────────────────────────────────────────────────────────

@router.post("/reset-password", response_model=MessageResponse)
async def reset_password(body: ResetPasswordRequest):
    r = get_redis()
    user_id = await r.get(f"pwd_reset:{sha256(body.token)}")
    if not user_id:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    users = get_collection("users")
    await users.update_one(
        {"_id": user_id},
        {"$set": {"password_hash": hash_password(body.new_password), "updated_at": utcnow()}},
    )
    await r.delete(f"pwd_reset:{sha256(body.token)}")
    return MessageResponse(success=True, message="Password reset successfully")


# ── Verify email ──────────────────────────────────────────────────────────────

@router.get("/verify-email/{token}", response_model=MessageResponse)
async def verify_email(token: str):
    r = get_redis()
    user_id = await r.get(f"email_verify:{sha256(token)}")
    if not user_id:
        raise HTTPException(status_code=400, detail="Invalid or expired verification link")

    users = get_collection("users")
    await users.update_one({"_id": user_id}, {"$set": {"email_verified": True, "updated_at": utcnow()}})
    await r.delete(f"email_verify:{sha256(token)}")
    return MessageResponse(success=True, message="Email verified successfully")
