from fastapi import APIRouter
from app.core.database import supabase

router = APIRouter(prefix="/admin/events", tags=["admin-events"])

@router.get("")
def list_events():
    return supabase.table("events") \
        .select("*") \
        .order("start_at", desc=True) \
        .execute().data
