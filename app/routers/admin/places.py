from fastapi import APIRouter, HTTPException
from datetime import datetime
from typing import List, Optional, Any
from app.core.database import supabase
from pydantic import BaseModel

class PlaceUpdatePayload(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None
    description: Optional[str] = None
    address: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    price_level: Optional[int] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    instagram: Optional[str] = None
    opening_hours: Optional[Any] = None
    cover_image: Optional[str] = None
    category_id: Optional[str] = None

router = APIRouter(
    prefix="/admin/places",
    tags=["admin-places"]
)

@router.get("")
def get_places(city_slug: str):
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
        # PLACES
        # -----------------------------
        places_raw = (
            supabase.table("places")
            .select("""
                id,
                name,
                slug,
                description,
                cover_image,
                address,
                lat,
                lng,
                price_level,
                open_hours_json,
                source_confidence,
                popularity,
                created_at,
                updated_at,
                categories:category_id (
                    id,
                    name,
                    slug
                )
            """)
            .eq("city_id", city_id)
            .order("name")
            .execute()
            .data
            or []
        )

        places = [
            {
                "id": p["id"],
                "name": p["name"],
                "slug": p["slug"],
                "description": p.get("description"),
                "image": p.get("cover_image"),
                "address": p.get("address"),
                "lat": p.get("lat"),
                "lng": p.get("lng"),
                "hasLocation": bool(p.get("lat") and p.get("lng")),
                "priceLevel": p.get("price_level"),
                "opening_hours": p.get("open_hours_json"),
                "source_confidence": p.get("source_confidence"),
                "popularity": p.get("popularity"),
                "category": p["categories"]["name"] if p.get("categories") else None,
                "category_slug": p["categories"]["slug"] if p.get("categories") else None,
                "category_id": p["categories"]["id"] if p.get("categories") else None,
                "created_at": p.get("created_at"),
                "updated_at": p.get("updated_at"),
            }
            for p in places_raw
        ]

        return {
            "city": city_slug,
            "count": len(places),
            "places": places,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/{place_id}")
def update_place(place_id: str, payload: PlaceUpdatePayload):
    try:
        # -----------------------------
        # CHECK PLACE
        # -----------------------------
        existing = (
            supabase.table("places")
            .select("id")
            .eq("id", place_id)
            .execute()
            .data
        )

        if not existing:
            raise HTTPException(status_code=404, detail="Place not found")

        # -----------------------------
        # BUILD UPDATE DATA
        # -----------------------------
        data = {
            k: v
            for k, v in payload.dict(exclude_unset=True).items()
        }

        if not data:
            raise HTTPException(status_code=400, detail="No fields to update")

        data["updated_at"] = datetime.utcnow().isoformat()

        # -----------------------------
        # UPDATE
        # -----------------------------
        updated = (
            supabase.table("places")
            .update(data)
            .eq("id", place_id)
            .execute()
            .data
        )

        return updated

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
