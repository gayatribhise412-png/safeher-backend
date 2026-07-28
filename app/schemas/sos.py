"""
Request / response schemas for SOS, location, and voice endpoints.
"""
from datetime import datetime
from pydantic import BaseModel, Field
from app.models.sos import SOSTriggerType, SOSStatus


class LocationInput(BaseModel):
    lat: float = Field(..., ge=-90.0, le=90.0)
    lng: float = Field(..., ge=-180.0, le=180.0)
    accuracy: float | None = None
    altitude: float | None = None
    speed: float | None = None
    heading: float | None = None
    address: str | None = None


class SOSCreateRequest(BaseModel):
    location: LocationInput | None = None
    trigger_type: SOSTriggerType = SOSTriggerType.MANUAL
    message: str | None = Field(None, max_length=500)
    audio_file_url: str | None = None
    ml_confidence: float | None = None


class SOSUpdateRequest(BaseModel):
    status: SOSStatus | None = None
    resolution_notes: str | None = None
    location: LocationInput | None = None


class SOSResponse(BaseModel):
    id: str
    user_id: str
    user_name: str
    status: str
    trigger_type: str
    location: dict | None
    tracking_url: str | None
    contacts_notified: int
    message: str | None
    created_at: datetime
    resolved_at: datetime | None


# ── Location tracking ─────────────────────────────────────────────────────────

class LocationUpdateRequest(BaseModel):
    lat: float = Field(..., ge=-90.0, le=90.0)
    lng: float = Field(..., ge=-180.0, le=180.0)
    accuracy: float | None = None
    speed: float | None = None
    heading: float | None = None
    session_id: str | None = None  # group pings into one tracking session


class NearbyPlacesRequest(BaseModel):
    lat: float = Field(..., ge=-90.0, le=90.0)
    lng: float = Field(..., ge=-180.0, le=180.0)
    radius_km: float = Field(default=5.0, ge=0.1, le=50.0)
    place_type: str = "all"   # police | hospital | shelter | all


# ── Voice / audio ─────────────────────────────────────────────────────────────

class VoiceAnalysisResponse(BaseModel):
    is_distress: bool
    is_scream: bool
    confidence: float
    emotion: str | None
    recommendation: str
    auto_sos_triggered: bool


# ── Chat ──────────────────────────────────────────────────────────────────────

class ChatMessageRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    session_id: str | None = None
    context: dict | None = None


class ChatMessageResponse(BaseModel):
    session_id: str
    user_message: str
    ai_response: str
    timestamp: datetime
    intent: str | None
    safety_action: str | None  # "trigger_sos" | "share_location" | None


# ── Fake call ─────────────────────────────────────────────────────────────────

class FakeCallRequest(BaseModel):
    caller_name: str = Field(default="Mom")
    caller_number: str = Field(default="+919876543210")
    delay_seconds: int = Field(default=0, ge=0, le=300)


# ── Notification ──────────────────────────────────────────────────────────────

class NotificationReadRequest(BaseModel):
    notification_ids: list[str] = Field(..., min_length=1)
