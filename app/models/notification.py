"""
Notification model — in-app notifications stored in notifications collection.
"""
from datetime import datetime
from typing import Optional
from enum import Enum
from pydantic import BaseModel, Field


class NotificationType(str, Enum):
    SOS_TRIGGERED = "sos_triggered"
    SOS_RESOLVED = "sos_resolved"
    CONTACT_ADDED = "contact_added"
    LOCATION_SHARED = "location_shared"
    SAFE_ZONE_ENTERED = "safe_zone_entered"
    SAFE_ZONE_EXITED = "safe_zone_exited"
    CHECK_IN_REMINDER = "check_in_reminder"
    MISSED_CHECK_IN = "missed_check_in"
    SECURITY_ALERT = "security_alert"
    SYSTEM = "system"
    AI_ALERT = "ai_alert"


class NotificationPriority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class NotificationModel(BaseModel):
    id: str = Field(default=None, alias="_id")
    user_id: str
    
    type: NotificationType = NotificationType.SYSTEM
    priority: NotificationPriority = NotificationPriority.NORMAL
    title: str
    body: str
    
    # Optional payload
    data: dict = Field(default_factory=dict)  # extra metadata (sos_id, location, etc.)
    action_url: Optional[str] = None
    icon: Optional[str] = None
    image_url: Optional[str] = None
    
    # State
    is_read: bool = False
    read_at: Optional[datetime] = None
    
    # Push delivery status
    push_sent: bool = False
    push_sent_at: Optional[datetime] = None
    push_error: Optional[str] = None
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None

    class Config:
        use_enum_values = True


# ── Factory helpers ───────────────────────────────────────────────────────────

def make_sos_notification(user_id: str, sos_id: str) -> dict:
    return {
        "user_id": user_id,
        "type": NotificationType.SOS_TRIGGERED,
        "priority": NotificationPriority.CRITICAL,
        "title": "🆘 SOS Alert Activated",
        "body": "Your emergency contacts are being notified with your live location.",
        "data": {"sos_id": sos_id},
        "action_url": f"/sos/{sos_id}",
    }


def make_safe_zone_notification(user_id: str, zone_name: str, entered: bool) -> dict:
    action = "entered" if entered else "exited"
    return {
        "user_id": user_id,
        "type": NotificationType.SAFE_ZONE_ENTERED if entered else NotificationType.SAFE_ZONE_EXITED,
        "priority": NotificationPriority.NORMAL,
        "title": f"📍 Safe Zone {'Entered' if entered else 'Exited'}",
        "body": f"You have {action} {zone_name}.",
        "data": {"zone_name": zone_name},
    }


def make_check_in_notification(user_id: str) -> dict:
    return {
        "user_id": user_id,
        "type": NotificationType.CHECK_IN_REMINDER,
        "priority": NotificationPriority.HIGH,
        "title": "⏰ Check-In Reminder",
        "body": "Your scheduled check-in is due. Let your contacts know you're safe.",
        "data": {},
    }
