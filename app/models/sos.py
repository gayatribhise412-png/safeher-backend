"""
SOS alert model — stored in sos_alerts collection.
Each document represents one SOS event with full lifecycle tracking.
"""
from datetime import datetime
from typing import Optional
from enum import Enum
from pydantic import BaseModel, Field


class SOSStatus(str, Enum):
    ACTIVE = "active"
    RESPONDED = "responded"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"
    FALSE_ALARM = "false_alarm"


class SOSTriggerType(str, Enum):
    MANUAL = "manual"           # User tapped SOS button
    VOICE = "voice"             # Scream/distress detected
    SHAKE = "shake"             # Phone shaking pattern
    SCHEDULED = "scheduled"     # Check-in missed
    AI_DETECTED = "ai_detected" # AI emotion/distress detected


class LocationSnapshot(BaseModel):
    lat: float
    lng: float
    accuracy: float = 0.0
    altitude: Optional[float] = None
    speed: Optional[float] = None
    heading: Optional[float] = None
    address: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class NotificationRecord(BaseModel):
    contact_id: str
    contact_name: str
    phone: str
    notified_at: datetime = Field(default_factory=datetime.utcnow)
    sms_sent: bool = False
    call_made: bool = False
    email_sent: bool = False
    whatsapp_sent: bool = False
    acknowledged: bool = False


class SOSModel(BaseModel):
    id: str = Field(default=None, alias="_id")
    user_id: str
    user_name: str
    user_phone: str | None = None

    # Trigger
    trigger_type: SOSTriggerType = SOSTriggerType.MANUAL
    status: SOSStatus = SOSStatus.ACTIVE

    # Location
    location: Optional[LocationSnapshot] = None
    location_history: list[LocationSnapshot] = Field(default_factory=list)

    # Message / audio
    message: str | None = None
    audio_file_url: str | None = None
    
    # Contacts notified
    notifications: list[NotificationRecord] = Field(default_factory=list)
    contacts_notified: int = 0

    # Tracking link
    tracking_token: str | None = None  # short token for sharable live-tracking URL
    tracking_url: str | None = None

    # Resolution
    resolved_at: datetime | None = None
    resolved_by: str | None = None       # "user" | "admin" | "timeout"
    resolution_notes: str | None = None

    # ML metadata
    ml_confidence: float | None = None   # confidence score from ML trigger
    ml_model: str | None = None

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        use_enum_values = True
        json_schema_extra = {
            "example": {
                "user_id": "507f1f77bcf86cd799439011",
                "trigger_type": "manual",
                "location": {"lat": 19.0760, "lng": 72.8777},
            }
        }
