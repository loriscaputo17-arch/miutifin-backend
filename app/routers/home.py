from fastapi import APIRouter, HTTPException
from app.core.database import supabase
from datetime import datetime, timezone
from typing import Optional
from dateutil.parser import isoparse
import httpx

router = APIRouter()


# -----------------------------
# HELPERS
# -----------------------------

def get_time_bucket(dt_iso: Optional[str]) -> Optional[str]:
    if not dt_iso:
        return None

    # Parsing ISO robusto (Supabase/Postgres safe)
    dt = isoparse(dt_iso)

    # Normalizziamo a UTC
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)

    hour = dt.hour
    weekday = dt.weekday()  # 0 = lunedì

    if weekday >= 4 and hour >= 18:
        return "weekend"

    if 18 <= hour < 23:
        return "tonight"

    if hour >= 23 or hour < 4:
        return "night"

    return "day"

def unique_by_id(items, used_ids, limit=None):
    result = []
    for item in items:
        if item["id"] in used_ids:
            continue
        used_ids.add(item["id"])
        result.append(item)
        if limit and len(result) >= limit:
            break
    return result


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
        city = (
            supabase.table("cities")
            .select("id, lat, lng")
            .eq("slug", city_slug)
            .single()
            .execute()
            .data
        )

        city_id = city["id"]

        now_utc = datetime.now(timezone.utc)

        used_event_ids = set()
        used_place_ids = set()

        # =============================
        # EVENTS
        # =============================
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
            .gte("start_at", now_utc.isoformat())
            .order("start_at")
            .limit(50)
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

        # --- Eventi weekend free
        events_weekend_free = unique_by_id(
            [e for e in events if e["timeBucket"] == "weekend" and e["priceLevel"] == 1],
            used_event_ids,
            limit=10,
        )

        # --- Eventi weekend paid
        events_weekend_paid = unique_by_id(
            [e for e in events if e["timeBucket"] == "weekend" and e["priceLevel"] and e["priceLevel"] > 1],
            used_event_ids,
            limit=10,
        )

        # --- Altri upcoming
        events_upcoming = unique_by_id(
            events,
            used_event_ids,
            limit=10,
        )

        # =============================
        # PLACES
        # =============================
        places_raw = (
            supabase.table("places")
            .select("""
                id,
                name,
                cover_image,
                lat,
                lng,
                address,
                price_level,
                categories(name)
            """)
            .eq("city_id", city_id)
            .limit(50)
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
                "address": p["address"],
                "hasLocation": bool(p["lat"] and p["lng"]),
                "isOpen": True,
                "type": "place",
            }
            for p in places_raw
        ]

        restaurants = unique_by_id(
            [p for p in places if p["category"] == "Restaurant"],
            used_place_ids,
            limit=10,
        )

        bars = unique_by_id(
            [p for p in places if p["category"] == "Bar"],
            used_place_ids,
            limit=10,
        )

        other_places = unique_by_id(
            places,
            used_place_ids,
            limit=10,
        )

        # =============================
        # MAP MARKERS
        # =============================
        markers = [
            {
                "id": item["id"],
                "lat": item["lat"],
                "lng": item["lng"],
                "title": item["title"],
                "category": item["category"],
                "type": item["type"],
            }
            for item in (
                events_weekend_free
                + events_weekend_paid
                + events_upcoming
                + restaurants
                + bars
                + other_places
            )
            if item.get("hasLocation")
        ]

        # =============================
        # RESPONSE
        # =============================
        return {
            "map": {
                "center": city,
                "markers": markers,
            },
            "sections": {
                "events_weekend_free": events_weekend_free,
                "events_weekend_paid": events_weekend_paid,
                "events_upcoming": events_upcoming,
                "restaurants": restaurants,
                "bars": bars,
                "places": other_places,
                "discover": [],
                "night_plans": [],
            },
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/by_neighborhood")
def by_neighborhood(city_slug: str):
    try:
        # -----------------------------
        # CITY
        # -----------------------------
        city = (
            supabase.table("cities")
            .select("id")
            .eq("slug", city_slug)
            .single()
            .execute()
            .data
        )

        if not city:
            raise HTTPException(status_code=404, detail="City not found")

        city_id = city["id"]

        # -----------------------------
        # QUERY (JOIN CORRETTI)
        # -----------------------------
        rows = (
            supabase.table("place_neighborhoods")
            .select("""
                neighborhoods (
                    id,
                    name,
                    city_id
                ),
                places (
                    id,
                    name,
                    cover_image,
                    lat,
                    lng,
                    address,
                    price_level,
                    categories ( name )
                )
            """)
            .eq("neighborhoods.city_id", city_id)
            .execute()
            .data
            or []
        )

        # -----------------------------
        # GROUPING
        # -----------------------------
        from collections import defaultdict

        grouped = defaultdict(list)

        for r in rows:
            neighborhood = r["neighborhoods"]
            place = r["places"]

            if not neighborhood or not place:
                continue

            grouped[neighborhood["name"]].append({
                "id": place["id"],
                "title": place["name"],
                "imageUrl": place["cover_image"],
                "category": (
                    place["categories"]["name"]
                    if place.get("categories")
                    else "Place"
                ),
                "priceLevel": place["price_level"],
                "lat": place["lat"],
                "lng": place["lng"],
                "address": place["address"],
                "hasLocation": bool(place["lat"] and place["lng"]),
                "type": "place",
            })

        # -----------------------------
        # RESPONSE
        # -----------------------------
        return [
            {
                "title": neighborhood,
                "items": items[:10]
            }
            for neighborhood, items in grouped.items()
        ]

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

