"""
Contact model for emergency_contacts collection.
"""
from datetime import datetime
from pydantic import BaseModel, Field


class ContactModel(BaseModel):
    """Emergency contact document."""
    id: str = Field(default=None, alias="_id")
    user_id: str
    
    name: str
    phone: str
    relation: str  # Mother, Father, Sister, Brother, Friend, Spouse, Other
    email: str | None = None
    
    is_trusted: bool = True
    priority: int = 1  # 1=highest priority (called first in SOS)
    
    # Notification preferences
    notify_via_sms: bool = True
    notify_via_call: bool = True
    notify_via_email: bool = False
    notify_via_whatsapp: bool = False
    
    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    last_notified: datetime | None = None
    notification_count: int = 0
    
    class Config:
        json_schema_extra = {
            "example": {
                "user_id": "507f1f77bcf86cd799439011",
                "name": "Mom",
                "phone": "+919876543210",
                "relation": "Mother",
                "priority": 1,
                "is_trusted": True,
            }
        }
