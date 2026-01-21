from fastapi import APIRouter
from typing import Optional
from app.core.database import supabase

router = APIRouter()

@router.get("/search")
def search(
    city_id: str,
    q: Optional[str] = None,
    limit: int = 10
):
    query = supabase.table("places").select("*").eq("city_id", city_id)

    if q:
        query = query.ilike("name", f"%{q}%")

    return query.limit(limit).execute().data
