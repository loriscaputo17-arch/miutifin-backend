from fastapi import APIRouter, HTTPException
from app.core.database import supabase
import re
from datetime import datetime

router = APIRouter(prefix="/places", tags=["places"])


# --------------------------------------------------
# Utils
# --------------------------------------------------
def normalize(text: str) -> str:
    return re.sub(
        r"[^a-z0-9 ]",
        "",
        text.lower()
    ).strip()


# --------------------------------------------------
# GET PLACE
# --------------------------------------------------
@router.get("/{place_id}")
def get_place(place_id: str):
    res = supabase.table("places") \
        .select("""
            id,
            name,
            description,
            address,
            cover_image,
            lat,
            lng,
            price_level,
            open_hours_json,
            categories(name),
            cities(name)
        """) \
        .eq("id", place_id) \
        .single() \
        .execute()

    if not res.data:
        raise HTTPException(status_code=404, detail="Place not found")

    p = res.data

    return {
        "id": p["id"],
        "name": p["name"],
        "description": p["description"],
        "address": p["address"],
        "cover_image": p["cover_image"],
        "lat": p["lat"],
        "lng": p["lng"],
        "price_level": p["price_level"],
        "open_hours": p["open_hours_json"],
        "category": p["categories"]["name"] if p.get("categories") else None,
        "city": p["cities"]["name"] if p.get("cities") else None,
        "rating": None,
        "reviews_count": 0,
        "images": [p["cover_image"]] if p["cover_image"] else [],
    }


# --------------------------------------------------
# GET EVENTS BY PLACE (venue_name similar)
# --------------------------------------------------
@router.get("/{place_id}/events")
def get_events_by_place(place_id: str):
    # 1️⃣ recupera il luogo
    place_res = supabase.table("places") \
        .select("name") \
        .eq("id", place_id) \
        .single() \
        .execute()

    if not place_res.data:
        raise HTTPException(status_code=404, detail="Place not found")

    place_name = place_res.data["name"]
    normalized_place = normalize(place_name)

    # 2️⃣ prendi eventi con venue_name valorizzato
    events_res = supabase.table("events") \
        .select("""
            id,
            title,
            start_at,
            venue_name,
            price_min,
            cover_image
        """) \
        .not_.is_("venue_name", "null") \
        .gte("start_at", datetime.utcnow().isoformat()) \
        .order("start_at") \
        .limit(6) \
        .execute()

    events = []

    for e in events_res.data or []:
        venue = e.get("venue_name")
        if not venue:
            continue

        if normalize(venue).find(normalized_place) != -1 or \
           normalized_place.find(normalize(venue)) != -1:
            events.append(e)

    return {
        "place": place_name,
        "events": events
    }

# --------------------------------------------------
# GET PLACE BY EVENT (inverse lookup)
# --------------------------------------------------
@router.get("/by-event/{event_id}")
def get_place_by_event(event_id: str):
    # 1️⃣ recupera l'evento
    event_res = supabase.table("events") \
        .select("venue_name") \
        .eq("id", event_id) \
        .single() \
        .execute()

    if not event_res.data:
        raise HTTPException(status_code=404, detail="Event not found")

    venue_name = event_res.data.get("venue_name")
    if not venue_name:
        return { "place": None }

    normalized_venue = normalize(venue_name)

    # 2️⃣ recupera tutti i places (id + name + lat/lng)
    places_res = supabase.table("places") \
        .select("id, name, lat, lng") \
        .execute()

    best_match = None

    for p in places_res.data or []:
        place_name = p.get("name")
        if not place_name:
            continue

        normalized_place = normalize(place_name)

        if (
            normalized_place in normalized_venue
            or normalized_venue in normalized_place
        ):
            best_match = p
            break

    if not best_match:
        return { "place": None }

    return {
        "place": {
            "id": best_match["id"],
            "name": best_match["name"],
            "lat": best_match["lat"],
            "lng": best_match["lng"],
        }
    }
