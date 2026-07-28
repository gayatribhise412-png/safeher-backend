"""
Request / response schemas for user and contact endpoints.
"""
from datetime import datetime
from pydantic import BaseModel, Field, EmailStr


class UserUpdateRequest(BaseModel):
    full_name: str | None = Field(None, min_length=2, max_length=100)
    phone: str | None = None
    city: str | None = None
    state: str | None = None
    country: str | None = None
    date_of_birth: datetime | None = None


class UpdateSettingsRequest(BaseModel):
    sos_sound: bool | None = None
    sos_vibration: bool | None = None
    auto_share_location: bool | None = None
    push_notifications: bool | None = None
    email_notifications: bool | None = None
    sms_notifications: bool | None = None
    dark_mode: bool | None = None
    language: str | None = None
    location_history_enabled: bool | None = None
    biometric_enabled: bool | None = None


class FCMTokenRequest(BaseModel):
    fcm_token: str


class UserResponse(BaseModel):
    id: str
    email: str
    full_name: str
    phone: str | None
    city: str | None
    state: str | None
    country: str
    profile_picture: str | None
    safety_score: int
    is_verified: bool
    is_premium: bool
    settings: dict
    created_at: datetime
    last_login: datetime | None


# ── Contact schemas ───────────────────────────────────────────────────────────

class ContactCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    phone: str = Field(..., description="E.164 phone number")
    relation: str = Field(..., description="Mother | Father | Sister | Friend | etc.")
    email: EmailStr | None = None
    priority: int = Field(default=1, ge=1, le=10)
    is_trusted: bool = True
    notify_via_sms: bool = True
    notify_via_call: bool = False
    notify_via_email: bool = False
    notify_via_whatsapp: bool = False


class ContactUpdateRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    phone: str | None = None
    relation: str | None = None
    email: EmailStr | None = None
    priority: int | None = Field(None, ge=1, le=10)
    is_trusted: bool | None = None
    notify_via_sms: bool | None = None
    notify_via_call: bool | None = None
    notify_via_email: bool | None = None
    notify_via_whatsapp: bool | None = None


class ContactResponse(BaseModel):
    id: str
    user_id: str
    name: str
    phone: str
    relation: str
    email: str | None
    is_trusted: bool
    priority: int
    notify_via_sms: bool
    notify_via_call: bool
    notify_via_email: bool
    notify_via_whatsapp: bool
    created_at: datetime
    last_notified: datetime | None
    notification_count: int
