"""
User model — MongoDB document structure.
Stored in 'users' collection.
"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, EmailStr


class UserModel(BaseModel):
    """Core user document."""
    id: str = Field(default=None, alias="_id")
    email: EmailStr
    phone: Optional[str] = None
    password_hash: str
    full_name: str
    
    # Profile
    profile_picture: Optional[str] = None
    date_of_birth: Optional[datetime] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: str = "India"
    
    # Safety
    safety_score: int = Field(default=85, ge=0, le=100)
    sos_contacts_count: int = 0
    
    # Flags
    is_active: bool = True
    is_verified: bool = False
    is_premium: bool = False
    email_verified: bool = False
    phone_verified: bool = False
    
    # Settings
    settings: dict = Field(default_factory=lambda: {
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
    })
    
    # Metadata
    role: str = "user"  # user | admin
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    last_login: Optional[datetime] = None
    last_location: Optional[dict] = None  # {"lat": float, "lng": float, "timestamp": datetime}
    
    # Device info
    fcm_tokens: list[str] = Field(default_factory=list)  # Firebase Cloud Messaging
    device_info: Optional[dict] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "email": "priya@example.com",
                "phone": "+919876543210",
                "full_name": "Priya Sharma",
                "city": "Mumbai",
                "state": "Maharashtra",
            }
        }


class EmergencyContact(BaseModel):
    """Embedded contact in emergency_contacts collection."""
    id: str = Field(default=None, alias="_id")
    user_id: str
    name: str
    phone: str
    relation: str  # Mother, Father, Sister, Friend, etc.
    is_trusted: bool = True
    priority: int = 1  # 1=highest, lower is contacted first in SOS
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        json_schema_extra = {
            "example": {
                "name": "Mom",
                "phone": "+919876500001",
                "relation": "Mother",
                "is_trusted": True,
                "priority": 1,
            }
        }
