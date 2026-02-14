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
            venue_name,
            categories(name),
            cities(name),
            places(name,lat,lng)
        """) \
        .eq("id", event_id) \
        .single() \
        .execute()

    if not res.data:
        raise HTTPException(status_code=404, detail="Event not found")

    e = res.data

    place_name = (
        e.get("venue_name")
        or (e["places"]["name"] if e.get("places") else None)
    )

    return {
        "id": e["id"],
        "title": e["title"],
        "description": e["description"],
        "cover_image": e["cover_image"],

        # ✅ gallery compatibile
        "images": [e["cover_image"]] if e["cover_image"] else [],

        "start_at": e["start_at"],
        "end_at": e["end_at"],
        "price_min": e["price_min"],
        "price_max": e["price_max"],

        # ✅ quello che la pagina usa davvero
        "category": e["categories"]["name"] if e.get("categories") else None,
        "city": e["cities"]["name"] if e.get("cities") else None,
        "place_name": place_name,

        "source_url": e["source_url"],
        "lat": e["lat"],
        "lng": e["lng"],
    }

@router.get("")
def search_events(
    city_slug: str = Query(...),
    q: Optional[str] = Query(None),
    filter: Optional[str] = Query(None),
):
    try:
        # ----------------------------
        # CITY
        # ----------------------------
        city_res = (
            supabase
            .table("cities")
            .select("id")
            .eq("slug", city_slug)
            .execute()
        )

        if not city_res.data:
            raise HTTPException(status_code=404, detail="City not found")

        city_id = city_res.data[0]["id"]

        # ----------------------------
        # BASE QUERY
        # ----------------------------
        now = datetime.utcnow().replace(second=0, microsecond=0)

        query = (
            supabase
            .table("events")
            .select("""
                id,
                title,
                cover_image,
                start_at,
                price_min,
                categories(name)
            """)
            .eq("city_id", city_id)
            # 🔒 SOLO eventi di oggi o futuri
            .gte("start_at", now.isoformat())
        )

        # ----------------------------
        # SEARCH
        # ----------------------------
        if q:
            query = query.ilike("title", f"%{q}%")

        # ----------------------------
        # FILTERS
        # ----------------------------
        if filter == "today":
            start = now.replace(hour=0, minute=0)
            end = start + timedelta(days=1)

            query = (
                query
                .gte("start_at", start.isoformat())
                .lt("start_at", end.isoformat())
            )

        elif filter == "weekend":
            saturday = now + timedelta((5 - now.weekday()) % 7)
            saturday = saturday.replace(hour=0, minute=0)
            monday = saturday + timedelta(days=2)

            query = (
                query
                .gte("start_at", saturday.isoformat())
                .lt("start_at", monday.isoformat())
            )

        elif filter == "free":
            query = query.eq("price_min", 0)

        # category filter (music, art, tech…)
        elif filter:
            query = query.eq("categories.name", filter)

        # ----------------------------
        # ORDER & LIMIT
        # ----------------------------
        query = query.order("start_at").limit(20)

        res = query.execute()

        # ----------------------------
        # FORMAT RESPONSE
        # ----------------------------
        events = [
            {
                "id": e["id"],
                "title": e["title"],
                "imageUrl": e["cover_image"],
                "category": (
                    e["categories"]["name"]
                    if e.get("categories")
                    else "Event"
                ),
                "type": "event",
                "isOpen": True,
            }
            for e in (res.data or [])
        ]

        return {
            "featured": events[:8],
            "items": events,
        }

    except HTTPException:
        raise

    except Exception as e:
        print("❌ search_events error:", str(e))

        raise HTTPException(
            status_code=500,
            detail="Error fetching events"
        )

@router.get("/{event_id}/similar")
def similar_events(event_id: str, limit: int = 6):
    base = supabase.table("events") \
        .select("id, city_id, category_id, start_at") \
        .eq("id", event_id) \
        .single() \
        .execute()

    if not base.data:
        raise HTTPException(404, "Event not found")

    e = base.data

    query = supabase.table("events") \
        .select("""
            id,
            title,
            cover_image,
            start_at,
            price_min,
            venue_name
        """) \
        .neq("id", event_id) \
        .gte("start_at", datetime.utcnow().isoformat())

    # 🔐 filtra SOLO se esiste
    if e.get("city_id"):
        query = query.eq("city_id", e["city_id"])

    if e.get("category_id"):
        query = query.eq("category_id", e["category_id"])

    res = query \
        .order("start_at") \
        .limit(limit) \
        .execute()

    return res.data
