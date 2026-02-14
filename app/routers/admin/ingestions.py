from fastapi import APIRouter
from app.core.database import supabase
from fastapi import HTTPException

router = APIRouter(prefix="/admin/ingestions", tags=["admin-ingestions"])

@router.get("")
def list_ingestions(limit: int = 20):
    res = supabase.table("ingestions") \
        .select("""
            id,
            status,
            started_at,
            ended_at,
            error,
            sources(name),
            cities(name, slug)
        """) \
        .order("started_at", desc=True) \
        .limit(limit) \
        .execute()

    return [
        {
            "id": i["id"],
            "status": i["status"],
            "source": i["sources"]["name"] if i.get("sources") else None,
            "city": i["cities"]["slug"] if i.get("cities") else None,
            "started_at": i["started_at"],
            "ended_at": i["ended_at"],
            "error": i["error"],
        }
        for i in res.data
    ]

@router.get("/{ingestion_id}/events")
def ingestion_events(ingestion_id: str):
    res = supabase.table("submissions") \
        .select("""
            id,
            title,
            start_at,
            venue_name,
            image
        """) \
        .eq("ingestion_id", ingestion_id) \
        .order("start_at") \
        .execute()

    if res.data is None:
        raise HTTPException(404, "Ingestion not found")

    return res.data

@router.get("/last")
def last_ingestion():
    ingestion = supabase.table("ingestions") \
        .select("id") \
        .order("started_at", desc=True) \
        .limit(1) \
        .single() \
        .execute()

    if not ingestion.data:
        return None

    events = supabase.table("submissions") \
        .select("id,title,start_at,venue_name,image") \
        .eq("ingestion_id", ingestion.data["id"]) \
        .execute()

    return {
        "ingestion_id": ingestion.data["id"],
        "events": events.data,
    }
