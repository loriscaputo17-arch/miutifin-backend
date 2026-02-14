from fastapi import APIRouter, HTTPException, Query
from typing import Optional, Dict, List, Tuple
from datetime import datetime
import hashlib
import json
import logging
import re

import pytz
import requests
from bs4 import BeautifulSoup
from slugify import slugify
from dateutil.relativedelta import relativedelta
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from app.core.database import supabase

from pydantic import BaseModel

class DiceIngestRequest(BaseModel):
    url: str
    city_slug: str
# ==================================================
# SETUP
# ==================================================

router = APIRouter(prefix="/ingestions", tags=["ingestions"])
logger = logging.getLogger(__name__)

SOURCE_NAME = "dice"

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

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "may": 5, "jun": 6, "jul": 7,
    "aug": 8, "sep": 9, "oct": 10,
    "nov": 11, "dec": 12,
    "gen": 1, "mag": 5, "giu": 6, "lug": 7,
    "ago": 8, "set": 9, "ott": 10, "dic": 12,
}

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

def parse_price(text: Optional[str]) -> Tuple[Optional[float], Optional[float]]:
    if not text:
        return None, None

    t = text.lower()
    if "gratis" in t or "free" in t:
        return 0, 0

    nums = [
        float(n.replace(",", "."))
        for n in re.findall(r"\d+(?:[.,]\d+)?", t)
    ]

    if not nums:
        return None, None

    return min(nums), max(nums)


def parse_dice_date(text: str, timezone: str) -> Optional[datetime]:
    if not text:
        return None

    tokens = text.lower().split("-")[0].split()
    if len(tokens) < 2:
        return None

    try:
        day = int(tokens[-2])
        month = MONTHS.get(tokens[-1][:3])
        if not month:
            return None

        tz = pytz.timezone(timezone)
        now = datetime.now(tz)

        dt = tz.localize(datetime(now.year, month, day, 21, 0))

        if dt < now - relativedelta(days=1):
            dt += relativedelta(years=1)

        return dt
    except Exception:
        return None

def extract_title(card):
    for sel in [
        "[class*='Title']",
        "[data-testid*='event-title']",
        "span",
        "div"
    ]:
        el = card.select_one(sel)
        if el and el.text.strip():
            return el.text.strip()
    return None

def extract_dice_events(html: str) -> List[Dict]:
    soup = BeautifulSoup(html, "html.parser")
    events = []

    for link in soup.select("a[href^='/event/']"):
        card = link.find_parent("div")
        if not card:
            continue

        def text(sel):
            el = card.select_one(sel)
            return el.text.strip() if el else None

        img = card.select_one("img")

        events.append({
            "source_url": "https://dice.fm" + link["href"],
            "title": extract_title(card),
            "date_text": text("[class*='Date']"),
            "venue": text("[class*='Venue']"),
            "price_text": text("[class*='Price']"),
            "image": img["src"] if img else None,
        })

    return events


def fetch_event_detail(url: str) -> Dict:
    r = session.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")

    def meta(prop):
        tag = soup.select_one(f"meta[property='{prop}']")
        return tag["content"] if tag else None

    return {
        "description": meta("og:description"),
        "image": meta("og:image"),
    }


# ==================================================
# API
# ==================================================

@router.post("/dice")
def ingest_dice(payload: DiceIngestRequest):
    url = payload.url
    city_slug = payload.city_slug

    if not url.startswith("https://dice.fm"):
        raise HTTPException(400, "Invalid DICE URL")

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
        raise HTTPException(400, "Source 'dice' not configured")

    city_id = city.data["id"]
    timezone = city.data["timezone"]
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
        r = session.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()

        items = extract_dice_events(r.text)

        existing = {
            s["source_url"]
            for s in supabase.table("submissions")
                .select("source_url")
                .eq("source", SOURCE_NAME)
                .eq("city_id", city_id)
                .execute().data
        }

        for item in items:
            if not item.get("title") or item["source_url"] in existing:
                skipped += 1
                continue

            try:
                detail = fetch_event_detail(item["source_url"])
                start_at = parse_dice_date(item["date_text"], timezone)
                price_min, price_max = parse_price(item["price_text"])

                payload = {
                    **item,
                    **detail,
                    "start_at": start_at.isoformat() if start_at else None,
                    "price_min": price_min,
                    "price_max": price_max,
                }

                # --------------------------
                # RAW ITEMS
                # --------------------------

                supabase.table("raw_items").insert({
                    "source_id": source_id,
                    "city_id": city_id,
                    "url": item["source_url"],
                    "checksum": checksum(payload),
                    "payload_json": payload,
                }).execute()

                # --------------------------
                # SUBMISSIONS
                # --------------------------

                description = (
                    detail["description"]
                    or " · ".join(
                        p for p in [
                            item["venue"],
                            item["date_text"],
                            item["price_text"],
                        ] if p
                    )
                )

                supabase.table("submissions").insert({
                    "city_id": city_id,
                    "source": SOURCE_NAME,
                    "source_url": item["source_url"],
                    "title": item["title"],
                    "description": description,

                    "start_at": start_at.isoformat() if start_at else None,
                    "end_at": None,
                    "price_min": price_min,
                    "price_max": price_max,
                    "venue_name": item["venue"],
                    "venue_address": None,
                    "source_payload": json_safe(payload),
                    "ingestion_id": ingestion_id,

                    "lat": None,
                    "lng": None,
                    "confidence": 60,
                    "status": "visible",
                    "image": detail["image"] or item["image"],
                }).execute()

                inserted += 1

            except Exception:
                logger.exception(f"Failed item {item['source_url']}")
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
        "found": len(items),
        "inserted": inserted,
        "skipped": skipped,
        "errors": errors,
    }
