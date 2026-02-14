from fastapi import APIRouter, Query, HTTPException
from typing import Optional
from app.core.database import supabase

router = APIRouter()

@router.get("/search")
def search(
    city_slug: str = Query(...),
    q: Optional[str] = Query(None),
    limit: int = 10
):
    # 1️⃣ risolvi city_id
    city_row = supabase.table("cities") \
        .select("id") \
        .eq("slug", city_slug) \
        .single() \
        .execute()

    if not city_row.data:
        raise HTTPException(404, "City not found")

    city_id = city_row.data["id"]

    items = []

    # ---------------- EVENTS ----------------
    if q:
        events = supabase.table("events") \
            .select("""
                id,
                title,
                start_at,
                price_min,
                venue_name
            """) \
            .eq("city_id", city_id) \
            .ilike("title", f"%{q}%") \
            .limit(limit) \
            .execute() \
            .data or []

        for e in events:
            items.append({
                "type": "event",
                "id": e["id"],
                "title": e["title"],
                "date": e["start_at"],
                "price": e["price_min"],
                "venue": e["venue_name"],
            })

    # ---------------- PLACES ----------------
    if q:
        places = supabase.table("places") \
            .select("""
                id,
                name,
                address
            """) \
            .eq("city_id", city_id) \
            .ilike("name", f"%{q}%") \
            .limit(limit) \
            .execute() \
            .data or []

        for p in places:
            items.append({
                "type": "place",
                "id": p["id"],
                "name": p["name"],
                "address": p.get("address"),
                "category": p["categories"]["name"] if p.get("categories") else None,
            })

    return {
        "items": items[:limit]
    }
