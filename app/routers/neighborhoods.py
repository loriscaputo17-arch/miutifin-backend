from fastapi import APIRouter, HTTPException
from app.core.database import supabase

router = APIRouter(tags=["neighborhoods"])

@router.get("/neighborhoods")
def get_neighborhoods(city: str):
    # -----------------------------
    # CITY
    # -----------------------------
    city_row = (
        supabase.table("cities")
        .select("id")
        .eq("slug", city)
        .single()
        .execute()
        .data
    )

    if not city_row:
        raise HTTPException(status_code=404, detail="City not found")

    city_id = city_row["id"]

    # -----------------------------
    # NEIGHBORHOODS
    # -----------------------------
    rows = (
        supabase.table("neighborhoods")
        .select("id, name, slug")
        .eq("city_id", city_id)
        .order("name")
        .execute()
        .data
        or []
    )

    # ⚠️ RITORNA **UN ARRAY PURO**
    return rows
