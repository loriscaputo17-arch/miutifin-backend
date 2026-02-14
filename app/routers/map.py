from fastapi import APIRouter, Query, HTTPException
from app.core.database import supabase

router = APIRouter(prefix="/map", tags=["map"])

@router.get("/markers")
def get_map_markers(
    city: str,
    bbox: str,
    zoom: int = 12,
    limit: int = 100,
    neighborhood: str = "all",
):
    try:
        min_lng, min_lat, max_lng, max_lat = map(float, bbox.split(","))
    except Exception:
        raise HTTPException(400, "Invalid bbox")

    city_row = (
        supabase.table("cities")
        .select("id")
        .eq("slug", city)
        .single()
        .execute()
        .data
    )

    if not city_row:
        raise HTTPException(404, "City not found")

    city_id = city_row["id"]

    zoom_limit = min(limit, 50 if zoom < 12 else 120)

    # =====================================
    # 1️⃣ FILTRO QUARTIERE → PLACE IDS
    # =====================================
    place_ids = None

    if neighborhood != "all":
        rows = (
            supabase.table("place_neighborhoods")
            .select("""
                place_id,
                neighborhoods!inner (
                    slug
                )
            """)
            .eq("neighborhoods.slug", neighborhood)
            .execute()
            .data
        )

        place_ids = [r["place_id"] for r in rows]

        if not place_ids:
            return {"markers": []}

    # =====================================
    # 2️⃣ QUERY PLACES (VERA)
    # =====================================
    query = (
        supabase.table("places")
        .select("""
            id,
            name,
            lat,
            lng,
            address,
            categories(name)
        """)
        .eq("city_id", city_id)
        .gte("lng", min_lng)
        .lte("lng", max_lng)
        .gte("lat", min_lat)
        .lte("lat", max_lat)
        .limit(zoom_limit)
    )

    if place_ids is not None:
        query = query.in_("id", place_ids)

    res = query.execute()

    markers = [
        {
            "id": p["id"],
            "lat": p["lat"],
            "lng": p["lng"],
            "title": p["name"],
            "address": p["address"],
            "category": (
                p["categories"]["name"]
                if p.get("categories")
                else "Place"
            ),
            "type": "place",
        }
        for p in res.data or []
        if p.get("lat") and p.get("lng")
    ]

    return {"markers": markers}
