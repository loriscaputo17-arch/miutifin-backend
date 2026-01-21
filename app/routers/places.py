from fastapi import APIRouter, HTTPException
from app.core.database import supabase

router = APIRouter(prefix="/places", tags=["places"])


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

        # 🔜 estendibili
        "rating": None,
        "reviews_count": 0,
        "images": [p["cover_image"]] if p["cover_image"] else [],
    }
