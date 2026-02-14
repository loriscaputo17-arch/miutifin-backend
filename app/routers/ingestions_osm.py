from fastapi import APIRouter, HTTPException
from typing import Dict, List
from datetime import datetime
import hashlib
import json
import logging
import requests
from slugify import slugify
from pydantic import BaseModel

from app.core.database import supabase

router = APIRouter(prefix="/ingestions", tags=["ingestions"])
logger = logging.getLogger(__name__)

SOURCE_NAME = "openstreetmap"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# --------------------------------------------------
# REQUEST MODEL
# --------------------------------------------------

class OSMIngestRequest(BaseModel):
    city_slug: str

# --------------------------------------------------
# UTILS
# --------------------------------------------------

def checksum(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()

# --------------------------------------------------
# OSM QUERY
# --------------------------------------------------

def build_overpass_query(lat: float, lng: float):
    return f"""
    [out:json];
    (
      node["amenity"~"bar|restaurant|cafe|pub|nightclub"](around:8000,{lat},{lng});
      way["amenity"~"bar|restaurant|cafe|pub|nightclub"](around:8000,{lat},{lng});
      node["leisure"="music_venue"](around:8000,{lat},{lng});
      way["leisure"="music_venue"](around:8000,{lat},{lng});
    );
    out center tags;
    """

# --------------------------------------------------
# CATEGORY MAPPING
# --------------------------------------------------

def map_category(tags: Dict) -> str | None:
    amenity = tags.get("amenity")
    leisure = tags.get("leisure")

    if amenity in ["bar", "pub"]:
        return "bar"
    if amenity == "restaurant":
        return "restaurant"
    if amenity == "cafe":
        return "cafe"
    if amenity == "nightclub":
        return "club"
    if leisure == "music_venue":
        return "live-music"

    return None

# --------------------------------------------------
# API
# --------------------------------------------------

@router.post("/osm")
def ingest_osm(payload: OSMIngestRequest):
    city_slug = payload.city_slug

    # ------------------------------
    # resolve city + source
    # ------------------------------
    city = supabase.table("cities") \
        .select("id, lat, lng") \
        .eq("slug", city_slug) \
        .single() \
        .execute()

    if not city.data:
        raise HTTPException(404, "City not found")

    source = supabase.table("sources") \
        .select("id") \
        .eq("name", SOURCE_NAME) \
        .single() \
        .execute()

    if not source.data:
        raise HTTPException(400, "Source 'openstreetmap' not configured")

    city_id = city.data["id"]
    lat = city.data["lat"]
    lng = city.data["lng"]
    source_id = source.data["id"]

    # ------------------------------
    # start ingestion
    # ------------------------------
    ingestion = supabase.table("ingestions").insert({
        "source_id": source_id,
        "city_id": city_id,
        "status": "running",
    }).execute()

    ingestion_id = ingestion.data[0]["id"]

    inserted = skipped = errors = 0

    try:
        query = build_overpass_query(lat, lng)
        r = requests.post(OVERPASS_URL, data=query, timeout=60)
        r.raise_for_status()
        data = r.json()

        for el in data.get("elements", []):
            try:
                tags = el.get("tags", {})
                name = tags.get("name")

                if not name:
                    skipped += 1
                    continue

                category_slug = map_category(tags)
                if not category_slug:
                    skipped += 1
                    continue

                lat_el = el.get("lat") or el.get("center", {}).get("lat")
                lng_el = el.get("lon") or el.get("center", {}).get("lon")

                payload = {
                    "name": name,
                    "tags": tags,
                    "lat": lat_el,
                    "lng": lng_el,
                }

                # --------------------------
                # RAW ITEMS
                # --------------------------
                supabase.table("raw_items").insert({
                    "source_id": source_id,
                    "city_id": city_id,
                    "url": f"osm:{el['id']}",
                    "checksum": checksum(payload),
                    "payload_json": payload,
                }).execute()

                # --------------------------
                # CATEGORY ID
                # --------------------------
                category = supabase.table("categories") \
                    .select("id") \
                    .eq("slug", category_slug) \
                    .single() \
                    .execute()

                if not category.data:
                    skipped += 1
                    continue

                # --------------------------
                # INSERT PLACE
                # --------------------------
                supabase.table("places").insert({
                    "city_id": city_id,
                    "category_id": category.data["id"],
                    "name": name,
                    "slug": slugify(name),
                    "description": tags.get("description"),
                    "address": tags.get("addr:full") or tags.get("addr:street"),
                    "lat": lat_el,
                    "lng": lng_el,
                    "cover_image": None,
                    "price_level": None,
                    "source_confidence": 50,
                }).execute()

                inserted += 1

            except Exception:
                logger.exception("Failed OSM element")
                errors += 1

        supabase.table("ingestions").update({
            "status": "success",
            "ended_at": datetime.utcnow().isoformat()
        }).eq("id", ingestion_id).execute()

    except Exception as e:
        supabase.table("ingestions").update({
            "status": "failed",
            "ended_at": datetime.utcnow().isoformat(),
            "error": str(e)
        }).eq("id", ingestion_id).execute()
        raise

    return {
        "source": SOURCE_NAME,
        "city": city_slug,
        "inserted": inserted,
        "skipped": skipped,
        "errors": errors,
    }
