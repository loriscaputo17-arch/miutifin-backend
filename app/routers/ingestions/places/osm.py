from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Dict, Optional, List
import httpx
import logging
from slugify import slugify

from app.core.database import supabase

router = APIRouter(prefix="/ingestions/places", tags=["ingestions"])
logger = logging.getLogger(__name__)

SOURCE_NAME = "openstreetmap"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# ==================================================
# REQUEST MODEL
# ==================================================

class OSMIngestRequest(BaseModel):
    city_slug: str


# ==================================================
# CATEGORY MAPPING
# ==================================================

OSM_CATEGORY_MAP = {
    "bar": ("bar", "Bar"),
    "pub": ("pub", "Pub"),
    "cafe": ("cafe", "Caffè"),
    "restaurant": ("restaurant", "Ristorante"),
    "fast_food": ("fast-food", "Fast Food"),
    "nightclub": ("nightclub", "Nightclub"),
    "biergarten": ("biergarten", "Birreria"),
}


def map_category(tags: Dict) -> Optional[Dict]:
    amenity = tags.get("amenity")
    if amenity in OSM_CATEGORY_MAP:
        slug, name = OSM_CATEGORY_MAP[amenity]
        return {"slug": slug, "name": name}
    return None


# ==================================================
# CATEGORY UPSERT
# ==================================================

def get_or_create_category(slug: str, name: str) -> Optional[str]:
    res = supabase.table("categories") \
        .select("id") \
        .eq("slug", slug) \
        .execute()

    if res.data:
        return res.data[0]["id"]

    created = supabase.table("categories").insert({
        "name": name,
        "slug": slug,
        "type": "place",
    }).execute()

    return created.data[0]["id"] if created.data else None


# ==================================================
# OSM FETCH (ASYNC)
# ==================================================

async def fetch_osm_places(lat: float, lng: float, radius_m: int = 8000) -> List[Dict]:
    query = f"""
    [out:json][timeout:60];
    (
      node(around:{radius_m},{lat},{lng})["amenity"];
      way(around:{radius_m},{lat},{lng})["amenity"];
    );
    out center tags;
    """

    async with httpx.AsyncClient(timeout=90) as client:
        r = await client.post(OVERPASS_URL, data=query)
        r.raise_for_status()
        return r.json().get("elements", [])


# ==================================================
# BACKGROUND INGESTION
# ==================================================

async def run_osm_ingestion(city_slug: str):
    logger.info(f"[OSM] Start ingestion for city={city_slug}")

    # ---- city ----
    city = supabase.table("cities") \
        .select("id, lat, lng") \
        .eq("slug", city_slug) \
        .single() \
        .execute()

    if not city.data:
        logger.error("[OSM] City not found")
        return

    city_id = city.data["id"]
    lat = city.data["lat"]
    lng = city.data["lng"]

    if lat is None or lng is None:
        logger.error("[OSM] City has no coordinates")
        return

    # ---- source ----
    source = supabase.table("sources") \
        .select("id") \
        .eq("name", SOURCE_NAME) \
        .execute()

    if source.data:
        source_id = source.data[0]["id"]
    else:
        created = supabase.table("sources").insert({
            "name": SOURCE_NAME,
            "type": "osm",
            "enabled": True,
        }).execute()
        source_id = created.data[0]["id"]

    # ---- fetch osm ----
    try:
        elements = await fetch_osm_places(lat, lng)
    except Exception:
        logger.exception("[OSM] Failed fetching OSM")
        return

    inserted = skipped = errors = 0

    for el in elements:
        try:
            tags = el.get("tags", {})
            name = tags.get("name")

            if not name:
                skipped += 1
                continue

            category_info = map_category(tags)
            if not category_info:
                skipped += 1
                continue

            category_id = get_or_create_category(
                slug=category_info["slug"],
                name=category_info["name"],
            )

            if not category_id:
                errors += 1
                continue

            lat_el = el.get("lat") or el.get("center", {}).get("lat")
            lng_el = el.get("lon") or el.get("center", {}).get("lon")

            if lat_el is None or lng_el is None:
                skipped += 1
                continue

            slug = slugify(name)

            supabase.table("places").upsert({
                "city_id": city_id,
                "category_id": category_id,
                "name": name,
                "slug": slug,
                "description": tags.get("description"),
                "address": tags.get("addr:full") or tags.get("addr:street"),
                "lat": lat_el,
                "lng": lng_el,
                "popularity": 0,
            }, on_conflict="city_id,slug").execute()

            inserted += 1

        except Exception:
            logger.exception("[OSM] Failed element")
            errors += 1

    logger.info(
        f"[OSM] Done city={city_slug} found={len(elements)} "
        f"inserted={inserted} skipped={skipped} errors={errors}"
    )


# ==================================================
# API (NON BLOCCANTE)
# ==================================================

@router.post("/osm")
async def ingest_osm(
    payload: OSMIngestRequest,
    background_tasks: BackgroundTasks,
):
    background_tasks.add_task(run_osm_ingestion, payload.city_slug)

    return {
        "status": "started",
        "source": SOURCE_NAME,
        "city": payload.city_slug,
        "message": "OSM ingestion running in background",
    }
