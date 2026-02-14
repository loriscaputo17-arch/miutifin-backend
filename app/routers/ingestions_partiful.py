from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Tuple
from datetime import datetime
import hashlib
import json
import logging
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from app.core.database import supabase

# ==================================================
# SETUP
# ==================================================

router = APIRouter(prefix="/ingestions", tags=["ingestions"])
logger = logging.getLogger(__name__)

SOURCE_NAME = "partiful"

session = requests.Session()
session.mount(
    "https://",
    HTTPAdapter(
        max_retries=Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
        )
    )
)

# ==================================================
# MODELS
# ==================================================

class PartifulIngestRequest(BaseModel):
    url: str
    city_slug: str

# ==================================================
# UTILS
# ==================================================

def checksum(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()

def json_safe(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [json_safe(v) for v in obj]
    return obj

def text(el):
    return el.get_text(strip=True) if el else None

# ==================================================
# PARSERS (PARTIFUL)
# ==================================================

def extract_title(soup: BeautifulSoup) -> Optional[str]:
    # titolo vero
    h1 = soup.select_one("h1 span.summary")
    if h1:
        return h1.get_text(strip=True)

    # fallback
    og = soup.select_one("meta[property='og:title']")
    if og:
        return og.get("content")

    return None

def extract_image(soup: BeautifulSoup) -> Optional[str]:
    # hero image principale
    img = soup.select_one("img[srcset]")
    if img:
        src = img.get("src")
        if src:
            return src

    og = soup.select_one("meta[property='og:image']")
    if og:
        return og.get("content")

    return None

def extract_datetime(soup: BeautifulSoup) -> Tuple[Optional[str], Optional[str]]:
    time_el = soup.select_one("time.dtstart")
    if not time_el:
        return None, None

    start_at = time_el.get("datetime")

    # end non affidabile → spesso solo testo
    return start_at, None

def extract_city_and_venue(soup: BeautifulSoup) -> Tuple[Optional[str], Optional[str]]:
    # es: "Milano Lombardia"
    loc = soup.select_one("span.ptf-tzbCO")
    if not loc:
        return None, None

    text_val = loc.get_text(" ", strip=True)
    return text_val, None

def extract_description(soup: BeautifulSoup) -> Optional[str]:
    # corpo descrizione grande
    blocks = soup.select("div.ptf-l-mWmFQ")
    if not blocks:
        return None

    return blocks[0].get_text("\n", strip=True)

# ==================================================
# FETCH PARTIFUL EVENT
# ==================================================

def fetch_partiful_event(url: str) -> Dict:
    r = session.get(
        url,
        timeout=10,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")

    title = extract_title(soup)
    description = extract_description(soup)
    image = extract_image(soup)
    start_at, end_at = extract_datetime(soup)
    venue, venue_address = extract_city_and_venue(soup)

    logger.info(
        f"PARTIFUL PARSED | title={bool(title)} start_at={start_at} image={bool(image)}"
    )

    return {
        "source_url": url,
        "title": title,
        "description": description,
        "start_at": start_at,
        "end_at": end_at,
        "price_min": None,
        "price_max": None,
        "venue": venue,
        "venue_address": venue_address,
        "image": image,
        "raw": {
            "title": title,
            "description": description,
            "start_at": start_at,
            "venue": venue,
            "image": image,
        },
    }

# ==================================================
# API
# ==================================================

@router.post("/partiful")
def ingest_partiful(payload: PartifulIngestRequest):
    url = payload.url
    city_slug = payload.city_slug

    # ------------------------------
    # resolve city + source
    # ------------------------------

    city = (
        supabase.table("cities")
        .select("id")
        .eq("slug", city_slug)
        .execute()
        .data
    )
    if not city:
        raise HTTPException(404, "City not found")

    source = (
        supabase.table("sources")
        .select("id")
        .eq("name", SOURCE_NAME)
        .execute()
        .data
    )
    if not source:
        raise HTTPException(400, "Source 'partiful' not configured")

    city_id = city[0]["id"]
    source_id = source[0]["id"]

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
        item = fetch_partiful_event(url)

        existing = {
            s["source_url"]
            for s in supabase.table("submissions")
            .select("source_url")
            .eq("source", SOURCE_NAME)
            .eq("city_id", city_id)
            .execute()
            .data
        }

        if item["source_url"] in existing:
            skipped += 1
        else:
            supabase.table("raw_items").insert({
                "source_id": source_id,
                "city_id": city_id,
                "url": item["source_url"],
                "checksum": checksum(item["raw"]),
                "payload_json": json_safe(item["raw"]),
            }).execute()

            supabase.table("submissions").insert({
                "city_id": city_id,
                "source": SOURCE_NAME,
                "source_url": item["source_url"],
                "title": item["title"] or "Partiful Event",
                "description": item["description"],
                "start_at": item["start_at"],
                "end_at": item["end_at"],
                "price_min": None,
                "price_max": None,
                "venue_name": item["venue"],
                "venue_address": item["venue_address"],
                "source_payload": json_safe(item["raw"]),
                "ingestion_id": ingestion_id,
                "lat": None,
                "lng": None,
                "confidence": 85,
                "status": "visible",
                "image": item["image"],
            }).execute()

            inserted += 1

        supabase.table("ingestions").update({
            "status": "success",
            "ended_at": datetime.utcnow().isoformat(),
        }).eq("id", ingestion_id).execute()

    except Exception as e:
        supabase.table("ingestions").update({
            "status": "failed",
            "ended_at": datetime.utcnow().isoformat(),
            "error": str(e),
        }).eq("id", ingestion_id).execute()
        raise

    return {
        "source": SOURCE_NAME,
        "city": city_slug,
        "url": url,
        "inserted": inserted,
        "skipped": skipped,
        "errors": errors,
    }
