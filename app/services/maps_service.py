"""
Google Maps service — geocoding, reverse geocoding, safe route analysis.
Falls back gracefully when API key is not configured.
"""
import logging
import httpx
from app.config import settings
from app.utils.helpers import haversine_km

logger = logging.getLogger("safeher.maps")

GMAPS_BASE = "https://maps.googleapis.com/maps/api"


class MapsService:

    @staticmethod
    async def reverse_geocode(lat: float, lng: float) -> str:
        """Return human-readable address for GPS coordinates."""
        if not settings.GOOGLE_MAPS_API_KEY:
            return f"{lat:.4f}, {lng:.4f}"

        url = f"{GMAPS_BASE}/geocode/json"
        params = {"latlng": f"{lat},{lng}", "key": settings.GOOGLE_MAPS_API_KEY}

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(url, params=params)
                data = r.json()
                if data["status"] == "OK" and data["results"]:
                    return data["results"][0]["formatted_address"]
        except Exception as exc:
            logger.warning("Reverse geocode failed: %s", exc)

        return f"{lat:.4f}, {lng:.4f}"


    @staticmethod
    async def geocode(address: str) -> dict | None:
        """Convert address string to GPS coordinates."""
        if not settings.GOOGLE_MAPS_API_KEY:
            return None

        url = f"{GMAPS_BASE}/geocode/json"
        params = {"address": address, "key": settings.GOOGLE_MAPS_API_KEY}

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(url, params=params)
                data = r.json()
                if data["status"] == "OK" and data["results"]:
                    loc = data["results"][0]["geometry"]["location"]
                    return {"lat": loc["lat"], "lng": loc["lng"], "address": data["results"][0]["formatted_address"]}
        except Exception as exc:
            logger.warning("Geocode failed: %s", exc)

        return None


    @staticmethod
    async def get_safe_route(
        origin_lat: float, origin_lng: float,
        dest_lat: float, dest_lng: float,
        mode: str = "walking",
    ) -> dict | None:
        """
        Get route from Google Directions API and enrich with safety metadata.
        """
        if not settings.GOOGLE_MAPS_API_KEY:
            # Return a stub route for demo
            dist_km = haversine_km(origin_lat, origin_lng, dest_lat, dest_lng)
            speed_kmh = {"walking": 5, "driving": 40, "transit": 30}.get(mode, 5)
            return {
                "distance_km": round(dist_km, 2),
                "duration_minutes": round(dist_km / speed_kmh * 60),
                "mode": mode,
                "safety_score": 85,
                "safety_label": "Safe",
                "waypoints": [],
                "polyline": None,
            }

        url = f"{GMAPS_BASE}/directions/json"
        params = {
            "origin": f"{origin_lat},{origin_lng}",
            "destination": f"{dest_lat},{dest_lng}",
            "mode": mode,
            "key": settings.GOOGLE_MAPS_API_KEY,
            "region": "in",
        }

        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                r = await client.get(url, params=params)
                data = r.json()

            if data["status"] != "OK":
                return None

            route = data["routes"][0]
            leg = route["legs"][0]

            # Basic safety scoring based on time of day and route type
            # (In production, enhance with crime data, street lighting APIs, etc.)
            safety_score = MapsService._estimate_safety_score(leg)

            return {
                "distance_km": round(leg["distance"]["value"] / 1000, 2),
                "duration_minutes": round(leg["duration"]["value"] / 60),
                "mode": mode,
                "safety_score": safety_score,
                "safety_label": "Safe" if safety_score >= 80 else "Moderate" if safety_score >= 60 else "Caution",
                "start_address": leg["start_address"],
                "end_address": leg["end_address"],
                "steps": len(leg["steps"]),
                "polyline": route["overview_polyline"]["points"],
            }

        except Exception as exc:
            logger.error("Directions API failed: %s", exc)
            return None


    @staticmethod
    async def nearby_places(
        lat: float, lng: float,
        place_type: str = "police",
        radius_m: int = 5000,
    ) -> list[dict]:
        """Query Google Places API for safe places nearby."""
        if not settings.GOOGLE_MAPS_API_KEY:
            return []

        url = f"{GMAPS_BASE}/place/nearbysearch/json"
        params = {
            "location": f"{lat},{lng}",
            "radius": radius_m,
            "type": place_type,
            "key": settings.GOOGLE_MAPS_API_KEY,
        }

        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                r = await client.get(url, params=params)
                data = r.json()

            if data["status"] not in ("OK", "ZERO_RESULTS"):
                return []

            results = []
            for place in data.get("results", [])[:10]:
                loc = place["geometry"]["location"]
                results.append({
                    "name": place["name"],
                    "type": place_type,
                    "lat": loc["lat"],
                    "lng": loc["lng"],
                    "address": place.get("vicinity"),
                    "rating": place.get("rating"),
                    "open_now": place.get("opening_hours", {}).get("open_now"),
                    "distance_km": round(haversine_km(lat, lng, loc["lat"], loc["lng"]), 2),
                })
            results.sort(key=lambda x: x["distance_km"])
            return results

        except Exception as exc:
            logger.error("Nearby places failed: %s", exc)
            return []


    @staticmethod
    def _estimate_safety_score(leg: dict) -> int:
        """
        Heuristic safety score from route metadata.
        Production: integrate Safegraph, OSM lighting data, crime APIs.
        """
        from datetime import datetime
        score = 75
        hour = datetime.now().hour
        # Night penalty
        if hour >= 22 or hour <= 5:
            score -= 20
        elif hour >= 20 or hour <= 7:
            score -= 10
        # Short routes are generally safer
        dist_km = leg["distance"]["value"] / 1000
        if dist_km < 1:
            score += 10
        elif dist_km > 5:
            score -= 5
        return max(20, min(score, 100))
