from fastapi import APIRouter, HTTPException
from app.core.database import supabase
from datetime import datetime
import httpx
from datetime import datetime
from typing import Optional

router = APIRouter()

def get_time_bucket(dt_iso: Optional[str]) -> Optional[str]:
    if not dt_iso:
        return None

    dt = datetime.fromisoformat(dt_iso.replace("Z", "+00:00"))
    hour = dt.hour
    weekday = dt.weekday()  # 0 = lunedì

    if weekday >= 4 and hour >= 18:
        return "weekend"

    if 18 <= hour < 23:
        return "tonight"

    if hour >= 23 or hour < 4:
        return "night"

    return "day"

def get_price_level(
    price_min: Optional[float],
    price_max: Optional[float]
) -> Optional[int]:
    if price_min is None and price_max is None:
        return None

    avg = ((price_min or 0) + (price_max or 0)) / 2

    if avg <= 15:
        return 1
    if avg <= 35:
        return 2
    return 3


# -----------------------------
# HOME ENDPOINT
# -----------------------------

@router.get("/home")
def home(city_slug: str):
    try:
        # -----------------------------
        # CITY
        # -----------------------------
        city_res = (
            supabase.table("cities")
            .select("id, lat, lng")
            .eq("slug", city_slug)
            .execute()
        )

        if not city_res.data:
            raise HTTPException(status_code=404, detail="City not found")

        city = city_res.data[0]
        city_id = city["id"]

        # -----------------------------
        # EVENTS
        # -----------------------------
        events_raw = (
            supabase.table("events")
            .select("""
                id,
                title,
                cover_image,
                start_at,
                source_url,
                lat,
                lng,
                price_min,
                price_max,
                categories(name)
            """)
            .eq("city_id", city_id)
            .order("start_at")
            .limit(20)
            .execute()
            .data
            or []
        )

        events = [
            {
                "id": e["id"],
                "title": e["title"],
                "imageUrl": e["cover_image"],
                "category": e["categories"]["name"] if e.get("categories") else "Event",
                "time": e["start_at"],
                "timeBucket": get_time_bucket(e["start_at"]),
                "priceLevel": get_price_level(e.get("price_min"), e.get("price_max")),
                "source_url": e["source_url"],
                "lat": e["lat"],
                "lng": e["lng"],
                "hasLocation": bool(e["lat"] and e["lng"]),
                "type": "event",
            }
            for e in events_raw
        ]

        # -----------------------------
        # PLACES
        # -----------------------------
        places_raw = (
            supabase.table("places")
            .select("""
                id,
                name,
                cover_image,
                lat,
                lng,
                price_level,
                categories(name)
            """)
            .eq("city_id", city_id)
            .limit(20)
            .execute()
            .data
            or []
        )

        places = [
            {
                "id": p["id"],
                "title": p["name"],
                "imageUrl": p["cover_image"],
                "category": p["categories"]["name"] if p.get("categories") else "Place",
                "priceLevel": p.get("price_level"),
                "lat": p["lat"],
                "lng": p["lng"],
                "hasLocation": bool(p["lat"] and p["lng"]),
                "isOpen": True,
                "type": "place",
            }
            for p in places_raw
        ]

        # -----------------------------
        # MAP MARKERS
        # -----------------------------
        markers = [
            {
                "id": item["id"],
                "lat": item["lat"],
                "lng": item["lng"],
                "title": item["title"],
                "category": item["category"],
                "type": item["type"],
            }
            for item in events + places
            if item.get("hasLocation")
        ]

        # -----------------------------
        # RESPONSE
        # -----------------------------
        return {
            "map": {
                "center": {
                    "lat": city["lat"],
                    "lng": city["lng"],
                },
                "markers": markers,
            },
            "sections": {
                "events_near_you": events,
                "bars": places,
                "discover": [],
                "night_plans": [],  # 🔜 journeys
            },
        }

    except httpx.ReadError:
        raise HTTPException(
            status_code=503,
            detail="Service temporarily unavailable",
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=str(e),
        )
