from fastapi import APIRouter, Query, HTTPException
from typing import Optional
from app.core.database import supabase

router = APIRouter(prefix="/plans", tags=["plans"])


@router.get("")
def search_plans(
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
    query = supabase.table("plans").select("""
        id,
        title,
        cover_image,
        slug,
        created_at
    """) \
    .eq("city_id", city_id) \
    .eq("visibility", "public")

    # --- SEARCH ---
    if q:
        query = query.ilike("title", f"%{q}%")

    # --- FILTERS (editorial) ---
    # Nota: questi sono "soft filters"
    if filter == "recent":
        query = query.order("created_at", desc=True)

    elif filter == "popular":
        query = query.order("created_at", desc=True)

    # fallback: nessun filtro rigido
    else:
        query = query.order("created_at", desc=True)

    query = query.limit(40)

    res = query.execute()

    plans = [
        {
            "id": p["id"],
            "title": p["title"],
            "imageUrl": p["cover_image"],
            "category": "Plan",
            "type": "plan",
            "isOpen": True,
        }
        for p in (res.data or [])
    ]

    # --- FEATURED (editorial choice) ---
    featured = plans[:8]

    return {
        "featured": featured,
        "items": plans,
    }
