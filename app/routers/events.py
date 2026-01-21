from fastapi import APIRouter, HTTPException, Query
from app.core.database import supabase
from datetime import datetime, timedelta
from typing import Optional

router = APIRouter(prefix="/events", tags=["events"])

@router.get("/{event_id}")
def get_event(event_id: str):
    res = supabase.table("events") \
        .select("""
            id,
            title,
            description,
            cover_image,
            start_at,
            end_at,
            source_url,
            price_min,
            price_max,
            lat,
            lng,
            categories(name),
            places(name,lat,lng)
        """) \
        .eq("id", event_id) \
        .single() \
        .execute()

    if not res.data:
        raise HTTPException(status_code=404, detail="Event not found")

    e = res.data

    return {
        "id": e["id"],
        "title": e["title"],
        "description": e["description"],
        "cover_image": e["cover_image"],
        "start_at": e["start_at"],
        "end_at": e["end_at"],
        "price_min": e["price_min"],
        "source_url": e["source_url"],
        "price_max": e["price_max"],
        "lat": e["lat"],
        "lng": e["lng"],
        "category": e["categories"]["name"] if e.get("categories") else None,
        "place": e["places"],
    }

@router.get("")
def search_events(
    city_slug: str = Query(...),
    q: Optional[str] = Query(None),
    filter: Optional[str] = Query(None),
):
    # --- CITY ---
    city_res = supabase.table("cities") \
        .select("id") \
        .eq("slug", city_slug) \
        .execute()

    if not city_res.data:
        raise HTTPException(status_code=404, detail="City not found")

    city_id = city_res.data[0]["id"]

    # --- BASE QUERY ---
    query = supabase.table("events").select("""
        id,
        title,
        cover_image,
        start_at,
        price_min,
        categories(name)
    """).eq("city_id", city_id)

    # --- SEARCH ---
    if q:
        query = query.ilike("title", f"%{q}%")

    now = datetime.utcnow()

    # --- FILTERS ---
    if filter == "today":
        start = now.replace(hour=0, minute=0, second=0)
        end = start + timedelta(days=1)
        query = query.gte("start_at", start.isoformat()).lte("start_at", end.isoformat())

    elif filter == "weekend":
        saturday = now + timedelta((5 - now.weekday()) % 7)
        sunday = saturday + timedelta(days=1)
        query = query.gte("start_at", saturday.isoformat()).lte("start_at", sunday.isoformat())

    elif filter == "free":
        query = query.eq("price_min", 0)

    # 👉 category filter (music, art, tech…)
    elif filter:
        query = query.ilike("categories.name", f"%{filter}%")

    # --- ORDER ---
    query = query.order("start_at").limit(40)

    res = query.execute()

    events = [
        {
            "id": e["id"],
            "title": e["title"],
            "imageUrl": e["cover_image"],
            "category": e["categories"]["name"] if e.get("categories") else "Event",
            "type": "event",
            "isOpen": True,
        }
        for e in (res.data or [])
    ]

    return {
        "featured": events[:8],
        "items": events,
    }