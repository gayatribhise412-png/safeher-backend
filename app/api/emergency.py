"""
Emergency numbers, services, and quick-dial endpoints.
"""
import logging
from fastapi import APIRouter, Depends, Query
from app.utils.dependencies import get_current_user
from app.utils.helpers import haversine_km

logger = logging.getLogger("safeher.emergency")
router = APIRouter(prefix="/emergency", tags=["Emergency Services"])

EMERGENCY_NUMBERS = [
    {"id": "police", "name": "Police", "number": "100", "icon": "🚔", "description": "Emergency police response", "available_24h": True},
    {"id": "ambulance", "name": "Ambulance", "number": "102", "icon": "🚑", "description": "Medical emergency services", "available_24h": True},
    {"id": "women_helpline", "name": "Women Helpline", "number": "1091", "icon": "👩‍⚕️", "description": "24/7 women safety helpline", "available_24h": True},
    {"id": "national_emergency", "name": "National Emergency", "number": "112", "icon": "🆘", "description": "All emergencies — police, fire, ambulance", "available_24h": True},
    {"id": "fire", "name": "Fire Brigade", "number": "101", "icon": "🚒", "description": "Fire emergency response", "available_24h": True},
    {"id": "child_helpline", "name": "Child Helpline", "number": "1098", "icon": "🧒", "description": "Child safety and abuse", "available_24h": True},
    {"id": "cyber_crime", "name": "Cyber Crime", "number": "1930", "icon": "💻", "description": "Online harassment and cyber crime", "available_24h": True},
    {"id": "domestic_violence", "name": "Domestic Violence", "number": "181", "icon": "🏠", "description": "Domestic abuse helpline", "available_24h": True},
    {"id": "road_accident", "name": "Road Accident", "number": "1073", "icon": "🚗", "description": "Road accident helpline", "available_24h": True},
    {"id": "senior_citizen", "name": "Senior Citizen", "number": "14567", "icon": "👴", "description": "Senior citizen helpline", "available_24h": True},
]

SAFE_PLACES_STATIC = [
    {"id": 1, "type": "police", "name": "Andheri Police Station", "city": "Mumbai", "address": "75, S.V. Road, Andheri West", "phone": "022-26201234", "lat": 19.1136, "lng": 72.8697, "rating": 4.2, "open_24h": True},
    {"id": 2, "type": "hospital", "name": "Kokilaben Dhirubhai Ambani Hospital", "city": "Mumbai", "address": "Rao Saheb Achutrao Patwardhan Marg", "phone": "022-30999999", "lat": 19.1359, "lng": 72.8271, "rating": 4.8, "open_24h": True},
    {"id": 3, "type": "hospital", "name": "Lilavati Hospital", "city": "Mumbai", "address": "A-791, Bandra Reclamation", "phone": "022-26751000", "lat": 19.0571, "lng": 72.8283, "rating": 4.7, "open_24h": True},
    {"id": 4, "type": "shelter", "name": "SNEHA Women Shelter", "city": "Mumbai", "address": "Sion, Mumbai", "phone": "1800-111-333", "lat": 19.0397, "lng": 72.8657, "rating": 4.6, "open_24h": True},
    {"id": 5, "type": "police", "name": "Bandra Police Station", "city": "Mumbai", "address": "Bandra West", "phone": "022-26401234", "lat": 19.0596, "lng": 72.8295, "rating": 4.0, "open_24h": True},
    {"id": 6, "type": "ngo", "name": "iCall Helpline — TISS", "city": "Mumbai", "address": "Tata Institute of Social Sciences", "phone": "9152987821", "lat": 19.0422, "lng": 72.8696, "rating": 4.5, "open_24h": False},
]


@router.get("/numbers")
async def get_emergency_numbers(current_user: dict = Depends(get_current_user)):
    return {"success": True, "data": EMERGENCY_NUMBERS}


@router.get("/numbers/{number_id}")
async def get_emergency_number(number_id: str, current_user: dict = Depends(get_current_user)):
    match = next((n for n in EMERGENCY_NUMBERS if n["id"] == number_id), None)
    if not match:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Emergency number not found")
    return {"success": True, "data": match}


@router.get("/safe-places")
async def get_safe_places(
    lat: float | None = Query(default=None),
    lng: float | None = Query(default=None),
    radius_km: float = Query(default=10.0, ge=0.1, le=50.0),
    place_type: str = Query(default="all"),
    current_user: dict = Depends(get_current_user),
):
    results = []
    for place in SAFE_PLACES_STATIC:
        if place_type != "all" and place["type"] != place_type:
            continue
        if lat is not None and lng is not None:
            dist = haversine_km(lat, lng, place["lat"], place["lng"])
            if dist > radius_km:
                continue
            place = {**place, "distance_km": round(dist, 2), "eta_minutes": round(dist / 5 * 60)}
        results.append(place)

    if lat and lng:
        results.sort(key=lambda x: x.get("distance_km", 0))

    return {"success": True, "data": results, "count": len(results)}


@router.get("/safety-tips")
async def get_safety_tips(
    category: str = Query(default="general"),
    current_user: dict = Depends(get_current_user),
):
    tips = {
        "general": [
            "Stay in well-lit and populated areas, especially at night.",
            "Share your travel plans and expected arrival time with someone you trust.",
            "Keep your phone charged — consider carrying a power bank.",
            "Trust your instincts. If something feels wrong, leave immediately.",
            "Memorise at least two emergency contacts without your phone.",
            "Be aware of your surroundings — avoid being distracted by your phone in public.",
        ],
        "travel": [
            "Share your live location before boarding a cab or auto.",
            "Verify cab driver details before getting in — check name, photo, and plate.",
            "Sit behind the driver — never in the front seat of a cab alone.",
            "Use well-lit and busy bus stops and metro stations.",
            "Avoid sleeping on public transport in isolated areas.",
        ],
        "online": [
            "Never share your real-time location on social media.",
            "Be cautious about sharing personal details with online strangers.",
            "Report cyberstalking or harassment to the Cyber Crime Helpline 1930.",
            "Use strong, unique passwords and enable two-factor authentication.",
        ],
        "home": [
            "Always verify visitors before opening the door.",
            "Keep emergency numbers saved and accessible.",
            "Have a home escape plan in case of danger.",
            "Keep a fully charged phone near your bed at night.",
        ],
    }
    selected = tips.get(category, tips["general"])
    return {"success": True, "data": selected, "category": category}
