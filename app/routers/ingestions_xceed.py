from fastapi import APIRouter, HTTPException
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import hashlib
import json
import logging
import re

import pytz
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dateutil import parser as dateparser

from pydantic import BaseModel

from app.core.database import supabase

# ==================================================
# SETUP
# ==================================================

router = APIRouter(prefix="/ingestions", tags=["ingestions"])
logger = logging.getLogger(__name__)

SOURCE_NAME = "xceed"
DEFAULT_TZ = "Europe/Rome"

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

class XceedIngestRequest(BaseModel):
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

def parse_prices(text: Optional[str]) -> Tuple[Optional[float], Optional[float]]:
    if not text:
        return None, None
    nums = re.findall(r"\d+(?:[.,]\d+)?", text)
    prices = [float(n.replace(",", ".")) for n in nums]
    if not prices:
        return None, None
    return min(prices), max(prices)

def parse_datetime(text: Optional[str], timezone: str) -> Optional[str]:
    if not text:
        return None
    try:
        tz = pytz.timezone(timezone)
        dt = dateparser.parse(text, fuzzy=True)
        if not dt:
            return None
        if not dt.tzinfo:
            dt = tz.localize(dt)
        return dt.isoformat()
    except Exception:
        return None

# ==================================================
# FETCH SINGLE XCEED EVENT (DOM-BASED)
# ==================================================

def fetch_xceed_event(url: str, timezone: str) -> Dict:
    r = session.get(
        url,
        timeout=10,
        headers={"User-Agent": "Mozilla/5.0"}
    )
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")

    def text(sel):
        el = soup.select_one(sel)
        return el.get_text(strip=True) if el else None

    # -----------------------------
    # EXTRACT FIELDS
    # -----------------------------

    title = text("h1")

    datetime_text = text("header p")
    start_at = parse_datetime(datetime_text, timezone)

    price_text = text("span:-soup-contains('€')")
    price_min, price_max = parse_prices(price_text)

    image = None
    img = soup.select_one("img[data-testid='image-custom']")
    if img:
        image = img.get("src")

    venue = text("section#venue h3")
    venue_address = text("section#venue p")

    description = text(
        "section#about div[data-testid='expandable-text-content']"
    )

    return {
        "source_url": url,
        "title": title,
        "description": description,
        "start_at": start_at,
        "end_at": None,
        "price_min": price_min,
        "price_max": price_max,
        "venue": venue,
        "venue_address": venue_address,
        "image": image,
        "raw": {
            "datetime_text": datetime_text,
            "price_text": price_text,
        }
    }

# ==================================================
# API
# ==================================================

@router.post("/xceed")
def ingest_xceed(payload: XceedIngestRequest):
    url = payload.url
    city_slug = payload.city_slug

    if not url.startswith("https://xceed.me/"):
        raise HTTPException(400, "Invalid Xceed URL")

    # ------------------------------
    # resolve city + source
    # ------------------------------

    city = supabase.table("cities") \
        .select("id, timezone") \
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
        raise HTTPException(400, "Source 'xceed' not configured")

    city_id = city.data["id"]
    timezone = city.data.get("timezone") or DEFAULT_TZ
    source_id = source.data["id"]

    # ------------------------------
    # start ingestion run
    # ------------------------------

    ingestion = supabase.table("ingestions").insert({
        "source_id": source_id,
        "city_id": city_id,
        "status": "running",
    }).execute()

    ingestion_id = ingestion.data[0]["id"]

    inserted = skipped = errors = 0

    try:
        item = fetch_xceed_event(url, timezone)

        existing = {
            s["source_url"]
            for s in supabase.table("submissions")
                .select("source_url")
                .eq("source", SOURCE_NAME)
                .eq("city_id", city_id)
                .execute().data
        }

        if not item["title"] or item["source_url"] in existing:
            skipped += 1
        else:
            payload_json = {
                k: item.get(k)
                for k in [
                    "source_url",
                    "title",
                    "description",
                    "start_at",
                    "end_at",
                    "price_min",
                    "price_max",
                    "venue",
                    "venue_address",
                    "image",
                ]
            }

            # --------------------------
            # RAW ITEMS
            # --------------------------

            supabase.table("raw_items").insert({
                "source_id": source_id,
                "city_id": city_id,
                "url": item["source_url"],
                "checksum": checksum(payload_json),
                "payload_json": json_safe(item["raw"]),
            }).execute()

            # --------------------------
            # SUBMISSIONS
            # --------------------------

            supabase.table("submissions").insert({
                "city_id": city_id,
                "source": SOURCE_NAME,
                "source_url": item["source_url"],
                "title": item["title"],
                "description": item["description"],
                "start_at": item["start_at"],
                "end_at": None,
                "price_min": item["price_min"],
                "price_max": item["price_max"],
                "venue_name": item["venue"],
                "venue_address": item["venue_address"],
                "source_payload": json_safe(item),
                "ingestion_id": ingestion_id,
                "lat": None,
                "lng": None,
                "confidence": 70,
                "status": "visible",
                "image": item["image"],
            }).execute()

            inserted += 1

        supabase.table("ingestions").update({
            "status": "success",
            "ended_at": datetime.utcnow().isoformat()
        }).eq("id", ingestion_id).execute()

    except Exception as e:
        logger.exception("Xceed ingestion failed")
        supabase.table("ingestions").update({
            "status": "failed",
            "ended_at": datetime.utcnow().isoformat(),
            "error": str(e)
        }).eq("id", ingestion_id).execute()
        raise

    return {
        "source": SOURCE_NAME,
        "city": city_slug,
        "found": 1,
        "inserted": inserted,
        "skipped": skipped,
        "errors": errors,
    }
