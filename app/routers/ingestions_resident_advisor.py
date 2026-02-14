from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Tuple, List
from datetime import datetime
import hashlib
import json
import logging
import re
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

SOURCE_NAME = "resident_advisor"

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

class RAIngestRequest(BaseModel):
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
# PARSERS (RESIDENT ADVISOR)
# ==================================================

def extract_title(soup: BeautifulSoup) -> Optional[str]:
    h1 = soup.select_one("header h1 span")
    if h1:
        return h1.get_text(strip=True)

    og = soup.select_one("meta[property='og:title']")
    return og.get("content") if og else None


def extract_image(soup: BeautifulSoup) -> Optional[str]:
    img = soup.select_one("picture img")
    if img and img.get("src"):
        return img["src"]

    og = soup.select_one("meta[property='og:image']")
    return og.get("content") if og else None


def extract_datetime(soup: BeautifulSoup) -> Tuple[Optional[str], Optional[str]]:
    date_el = soup.select_one("[data-pw-test-id='event-date'], a[href*='startDate']")
    time_els = soup.select("span")

    date_text = None
    start_time = None
    end_time = None

    # es: "mer, 25 feb 2026"
    for a in soup.select("a[href*='startDate']"):
        date_text = a.get_text(strip=True)

    # es: "23:59 - 05:00"
    times = [
        s.get_text(strip=True)
        for s in soup.select("span")
        if re.match(r"\d{2}:\d{2}", s.get_text(strip=True))
    ]

    if times:
        start_time = times[0]
        end_time = times[1] if len(times) > 1 else None

    if not date_text:
        return None, None

    try:
        # fallback robusto → RA ha timezone locale
        start_at = f"{date_text} {start_time}" if start_time else date_text
        return start_at, None
    except Exception:
        return None, None


def extract_venue(soup: BeautifulSoup) -> Tuple[Optional[str], Optional[str]]:
    venue = soup.select_one("[data-pw-test-id='event-venue-link']")
    venue_name = text(venue)

    address = soup.select_one("span:contains('Italy')")
    venue_address = text(address)

    return venue_name, venue_address


def extract_lineup(soup: BeautifulSoup) -> Optional[str]:
    lineup_block = soup.select_one("[data-tracking-id='event-detail-lineup']")
    if not lineup_block:
        return None

    artists = lineup_block.select("span")
    names = [a.get_text(strip=True) for a in artists if a.get_text(strip=True)]
    return ", ".join(names) if names else None


def extract_genres(soup: BeautifulSoup) -> List[str]:
    tags = soup.select(".Tag__TagStyled-sc-128nata-0")
    return [t.get_text(strip=True) for t in tags]


def extract_description(soup: BeautifulSoup) -> Optional[str]:
    desc = soup.select_one("[data-tracking-id='event-detail-description']")
    if not desc:
        return None

    return desc.get_text("\n", strip=True)

# ==================================================
# FETCH RA EVENT
# ==================================================

def fetch_ra_event(url: str) -> Dict:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/121.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;"
            "q=0.9,image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://it.ra.co/",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }

    r = session.get(
        url,
        headers=headers,
        timeout=15,
    )

    if r.status_code == 403:
        logger.error("RA BLOCKED REQUEST (403)")
        raise HTTPException(
            status_code=502,
            detail="Resident Advisor blocked the request (anti-bot)"
        )

    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    title = extract_title(soup)
    description = extract_description(soup)
    image = extract_image(soup)
    start_at, end_at = extract_datetime(soup)
    venue, venue_address = extract_venue(soup)
    lineup = extract_lineup(soup)
    genres = extract_genres(soup)

    logger.info(
        f"RA PARSED | title={bool(title)} venue={venue} image={bool(image)}"
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
            "venue_address": venue_address,
            "lineup": lineup,
            "genres": genres,
            "image": image,
        },
    }

# ==================================================
# API
# ==================================================

@router.post("/resident_advisor")
def ingest_resident_advisor(payload: RAIngestRequest):
    url = payload.url
    city_slug = payload.city_slug

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
        raise HTTPException(400, "Source 'resident_advisor' not configured")

    city_id = city[0]["id"]
    source_id = source[0]["id"]

    ingestion = supabase.table("ingestions").insert({
        "source_id": source_id,
        "city_id": city_id,
        "status": "running",
    }).execute()

    ingestion_id = ingestion.data[0]["id"]

    inserted = skipped = errors = 0

    try:
        item = fetch_ra_event(url)

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
                "title": item["title"] or "Resident Advisor Event",
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
                "confidence": 90,
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
