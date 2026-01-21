from fastapi import APIRouter, HTTPException
from app.core.database import supabase
from datetime import datetime
import re
from typing import Optional

router = APIRouter(prefix="/submissions", tags=["submissions"])

# --------------------------------------------------
# Utils
# --------------------------------------------------

def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"\s+", "-", text)
    return text.strip("-")


# --------------------------------------------------
# GET /submissions
# --------------------------------------------------

@router.get("")
def list_submissions(
    city_id: Optional[str] = None,
    status: Optional[str] = None,
    source: Optional[str] = None,
):
    q = supabase.table("submissions") \
        .select("""
            id,
            title,
            source,
            confidence,
            status,
            created_at,
            categories(name)
        """) \
        .order("created_at", desc=True)

    if city_id:
        q = q.eq("city_id", city_id)

    if status:
        q = q.eq("status", status)

    if source:
        q = q.eq("source", source)

    res = q.execute()
    return res.data or []


# --------------------------------------------------
# GET /submissions/{id}
# --------------------------------------------------

@router.get("/{submission_id}")
def get_submission(submission_id: str):
    res = supabase.table("submissions") \
        .select("""
            *,
            categories(name)
        """) \
        .eq("id", submission_id) \
        .single() \
        .execute()

    if not res.data:
        raise HTTPException(404, "Submission not found")

    return res.data


# --------------------------------------------------
# POST /submissions/{id}/promote
# --------------------------------------------------

@router.post("/{submission_id}/promote")
def promote_submission(submission_id: str):
    # ---- fetch submission
    sub_res = supabase.table("submissions") \
        .select("*") \
        .eq("id", submission_id) \
        .single() \
        .execute()

    if not sub_res.data:
        raise HTTPException(404, "Submission not found")

    s = sub_res.data

    if s["status"] == "promoted":
        raise HTTPException(400, "Submission already promoted")

    slug = slugify(s["title"])
    now_iso = datetime.utcnow().isoformat()

    # ---- create event
    event_res = supabase.table("events").insert({
        "city_id": s["city_id"],
        "category_id": s["category_id"],
        "title": s["title"],
        "slug": slug,
        "description": s["description"],
        "source_url": s.get("source_url"),     # ✅ PROMOSSO
        "start_at": now_iso,
        "cover_image": s.get("image"),          # ✅ IMAGE → COVER
        "price_min": None,
        "price_max": None,
        "lat": s["lat"],
        "lng": s["lng"],
    }).execute()

    if not event_res.data:
        raise HTTPException(500, "Failed to create event")

    event_id = event_res.data[0]["id"]

    # ---- update submission
    supabase.table("submissions").update({
        "status": "promoted",
        "promoted_entity_type": "event",
        "promoted_entity_id": event_id,
        "updated_at": now_iso,
    }).eq("id", submission_id).execute()

    return {
        "status": "ok",
        "event_id": event_id
    }
