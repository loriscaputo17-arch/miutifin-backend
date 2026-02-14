from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict
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

SOURCE_NAME = "eventbrite"

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

class EventbriteIngestRequest(BaseModel):
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
# PARSERS
# ==================================================

def extract_title(soup: BeautifulSoup) -> Optional[str]:
    selectors = [
        "h1.event-title",
        "h1[data-testid='event-title']",
        "div[data-testid='title'] h1",
        "h1",
        "meta[property='og:title']",
    ]
    for sel in selectors:
        el = soup.select_one(sel)
        if el:
            if el.name == "meta":
                return el.get("content")
            t = el.get_text(strip=True)
            if t:
                return t
    return None

def extract_description(soup: BeautifulSoup) -> Optional[str]:
    el = soup.select_one("#event-description")
    if el:
        return el.get_text("\n", strip=True)

    og = soup.select_one("meta[property='og:description']")
    return og["content"] if og else None

def extract_image(soup: BeautifulSoup) -> Optional[str]:
    og = soup.select_one("meta[property='og:image']")
    if og and og.get("content"):
        return og["content"]

    img = soup.select_one("img[data-testid='hero-img']")
    if img:
        if img.get("src"):
            return img["src"]
        if img.get("srcset"):
            return img["srcset"].split(",")[-1].split()[0]

    bg = soup.select_one(".event-hero__background")
    if bg and bg.get("style"):
        m = re.search(r'url\("([^"]+)"\)', bg["style"])
        if m:
            return m.group(1)

    return None

def extract_datetime(soup: BeautifulSoup):
    time_el = soup.select_one("time.start-date-and-location__date")
    if not time_el:
        return None, None

    start = time_el.get("datetime")
    text_val = time_el.get_text(strip=True)

    end = None
    if " to " in text_val:
        # non affidabile → meglio None
        end = None

    return start, end

def extract_price(soup: BeautifulSoup):
    price = None
    el = soup.select_one("[data-testid='condensed-conversion-bar'] span")
    if el:
        m = re.search(r"€\s?([\d.,]+)", el.get_text())
        if m:
            price = float(m.group(1).replace(",", "."))
    return price, price

def extract_venue(soup: BeautifulSoup):
    venue = text(soup.select_one(".start-date-and-location__location"))
    address_lines = soup.select(
        ".Location-module__addressText___2Qq8L, "
        ".Location-module__addressAdditionalLine___23C25"
    )
    address = ", ".join(a.get_text(strip=True) for a in address_lines) if address_lines else None
    return venue, address

# ==================================================
# FETCH EVENT
# ==================================================

def fetch_eventbrite_event(url: str) -> Dict:
    r = session.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")

    title = extract_title(soup)
    description = extract_description(soup)
    image = extract_image(soup)
    start_at, end_at = extract_datetime(soup)
    price_min, price_max = extract_price(soup)
    venue, venue_address = extract_venue(soup)

    return {
        "source_url": url,
        "title": title,
        "description": description,
        "start_at": start_at,
        "end_at": end_at,
        "price_min": price_min,
        "price_max": price_max,
        "venue": venue,
        "venue_address": venue_address,
        "image": image,
        "raw": {
            "title": title,
            "description": description,
            "start_at": start_at,
            "end_at": end_at,
            "price_min": price_min,
            "price_max": price_max,
            "venue": venue,
            "venue_address": venue_address,
            "image": image,
        }
    }

# ==================================================
# API
# ==================================================

@router.post("/eventbrite")
def ingest_eventbrite(payload: EventbriteIngestRequest):
    url = payload.url
    city_slug = payload.city_slug

    city = supabase.table("cities").select("id").eq("slug", city_slug).execute().data
    if not city:
        raise HTTPException(404, "City not found")

    source = supabase.table("sources").select("id").eq("name", SOURCE_NAME).execute().data
    if not source:
        raise HTTPException(400, "Source 'eventbrite' not configured")

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
        item = fetch_eventbrite_event(url)

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
                "title": item["title"] or "Eventbrite Event",
                "description": item["description"],
                "start_at": item["start_at"],
                "end_at": item["end_at"],
                "price_min": item["price_min"],
                "price_max": item["price_max"],
                "venue_name": item["venue"],
                "venue_address": item["venue_address"],
                "source_payload": json_safe(item["raw"]),
                "ingestion_id": ingestion_id,
                "lat": None,
                "lng": None,
                "confidence": 80,
                "status": "visible",
                "image": item["image"],
            }).execute()

            inserted += 1

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
        "url": url,
        "inserted": inserted,
        "skipped": skipped,
        "errors": errors,
    }
