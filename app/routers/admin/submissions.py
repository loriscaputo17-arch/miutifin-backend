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

def unique_event_slug(city_id: str, base: str) -> str:
    slug = base
    i = 1

    while True:
        exists = supabase.table("events") \
            .select("id") \
            .eq("city_id", city_id) \
            .eq("slug", slug) \
            .execute()

        if not exists.data:
            return slug

        i += 1
        slug = f"{base}-{i}"

@router.get("/submissions")
def list_submissions():
    return supabase.table("submissions") \
        .select("*") \
        .order("created_at", desc=True) \
        .execute().data

@router.post("/submissions/{submission_id}/promote/event")
def promote_submission_to_event(submission_id: str):
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

    # invece di bloccare
    if not s.get("start_at"):
        start_at = None
    else:
        start_at = s["start_at"]

    base_slug = slugify(s["title"])
    slug = unique_event_slug(s["city_id"], base_slug)

    now_iso = datetime.utcnow().isoformat()

    # ---- create event
    event_res = supabase.table("events").insert({
        "city_id": s["city_id"],
        "place_id": None,  # ⚠️ lo collegherai dopo
        "category_id": s["category_id"],
        "title": s["title"],
        "slug": slug,
        "description": s["description"],

        # ✅ DATI EVENTO REALI
        "start_at": s["start_at"],
        "end_at": s["end_at"],
        "price_min": s["price_min"],
        "price_max": s["price_max"],

        # ✅ VENUE (NUOVO)
        "venue_name": s.get("venue_name"),

        # ✅ MEDIA / SOURCE
        "cover_image": s["image"],
        "source_url": s["source_url"],

        # ✅ GEO
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
        "event_id": event_id,
        "slug": slug,
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

@router.put("/events/{event_id}")
def update_event(event_id: str, payload: dict):
    # ---- fetch event
    event_res = supabase.table("events") \
        .select("*") \
        .eq("id", event_id) \
        .single() \
        .execute()

    if not event_res.data:
        raise HTTPException(404, "Event not found")

    e = event_res.data

    updates = {}
    now_iso = datetime.utcnow().isoformat()

    # ---- title + slug
    if "title" in payload and payload["title"] != e["title"]:
        base_slug = slugify(payload["title"])
        slug = unique_event_slug(e["city_id"], base_slug)

        updates["title"] = payload["title"]
        updates["slug"] = slug

    # ---- simple fields
    for field in [
        "description",
        "start_at",
        "end_at",
        "price_min",
        "price_max",
        "venue_name",
        "cover_image",
        "source_url",
        "lat",
        "lng",
        "category_id",
        "place_id",
    ]:
        if field in payload:
            updates[field] = payload[field]

    if not updates:
        return e  # niente da aggiornare

    updates["updated_at"] = now_iso

    # ---- update
    res = supabase.table("events") \
        .update(updates) \
        .eq("id", event_id) \
        .execute()

    if not res.data:
        raise HTTPException(500, "Failed to update event")

    return res.data[0]
