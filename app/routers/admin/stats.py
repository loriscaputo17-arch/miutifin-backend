from fastapi import APIRouter
from app.core.database import supabase

router = APIRouter(prefix="/admin", tags=["admin"])

@router.get("/stats")
def get_admin_stats():
    def count(table: str):
        return supabase.table(table).select("id", count="exact").execute().count

    users = supabase.table("profiles").select("id", count="exact").execute().count

    waitlist_total = supabase.table("waitlist") \
        .select("id", count="exact") \
        .execute().count

    waitlist_pending = supabase.table("waitlist") \
        .select("id", count="exact") \
        .eq("status", "pending") \
        .execute().count

    return {
        "users": users,
        "events": count("events"),
        "submissions": count("submissions"),
        "places": count("places"),
        "waitlist": {
            "total": waitlist_total,
            "pending": waitlist_pending,
        }
    }

