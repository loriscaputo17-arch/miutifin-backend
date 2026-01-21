from fastapi import APIRouter, HTTPException
from app.core.database import supabase
from datetime import datetime
import re
from typing import Optional

router = APIRouter(prefix="/admin", tags=["admin"])

def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"\s+", "-", text)
    return text.strip("-")

@router.get("/submissions")
def list_submissions():
    return supabase.table("submissions") \
        .select("*") \
        .eq("status", "draft") \
        .order("created_at", desc=True) \
        .execute().data

@router.post("/submissions/{submission_id}/promote/event")
def promote_submission_to_event(submission_id: str):
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


@router.post("/submissions/{id}/promote/place")
def promote_submission_to_place(id: str):
    s = supabase.table("submissions") \
        .select("*") \
        .eq("id", id) \
        .single() \
        .execute().data

    if not s:
        raise HTTPException(404, "Submission not found")

    place = supabase.table("places").insert({
        "city_id": s["city_id"],
        "name": s["title"],
        "description": s["description"],
        "lat": s["lat"],
        "lng": s["lng"],
        "source_confidence": s["confidence"]
    }).execute().data[0]

    supabase.table("submissions").update({
        "status": "promoted"
    }).eq("id", id).execute()

    return place
