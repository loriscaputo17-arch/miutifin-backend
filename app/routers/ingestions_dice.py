from fastapi import APIRouter, HTTPException, Query
from app.core.database import supabase
from bs4 import BeautifulSoup
from urllib.parse import urlparse
import requests

router = APIRouter(prefix="/ingestions", tags=["ingestions"])


# --------------------------------------------------
# CATEGORY INFERENCE (ALIGNED WITH DB)
# --------------------------------------------------

def infer_category_slug_from_dice_url(url: str) -> str:
    """
    Returns a category.slug that MUST exist in categories (type=event)
    """
    path = urlparse(url).path.lower().strip("/")
    parts = path.split("/")

    # -------- MUSIC --------
    if "music" in parts:
        if any(p in parts for p in ["dj", "party", "afrohouse", "house", "techno"]):
            return "club-night"

        if any(p in parts for p in ["gig", "live", "band"]):
            return "concert"

        return "live-music"

    # -------- CULTURE --------
    if "culture" in parts:
        if "film" in parts or "cinema" in parts:
            return "cinema"

        if "comedy" in parts:
            return "comedy"

        if "theatre" in parts:
            return "theatre"

        if "art" in parts:
            return "art"

        if "foodanddrink" in parts:
            return "food-drink"

        if "sport" in parts:
            return "sport"

        if "social" in parts:
            return "social"

        return "event"

    # -------- FESTIVAL --------
    if "festival" in parts:
        return "festival"

    return "event"


# --------------------------------------------------
# HTML PARSER (DICE)
# --------------------------------------------------

def extract_dice_events_from_html(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("div.EventCard__Event-sc-5ea8797e-1")

    events: list[dict] = []

    for card in cards:
        link = card.select_one("a[href^='/event/']")
        if not link:
            continue

        def text(selector: str):
            el = card.select_one(selector)
            return el.text.strip() if el else None

        img_el = card.select_one("div.styles__ImageWrapper-sc-4cc6fa9-2 img")
        image_url = img_el["src"] if img_el and img_el.has_attr("src") else None

        events.append({
            "source_url": "https://dice.fm" + link["href"],
            "title": text(".styles__Title-sc-4cc6fa9-6"),
            "date_text": text(".styles__DateText-sc-4cc6fa9-8"),
            "venue_name": text(".styles__Venue-sc-4cc6fa9-7"),
            "price_text": text(".styles__Price-sc-4cc6fa9-9"),
            "image": image_url,
        })

    return events


# --------------------------------------------------
# API ENDPOINT
# --------------------------------------------------

@router.post("/dice")
def ingest_dice(
    url: str = Query(..., description="Dice browse URL"),
    city_slug: str = Query(..., description="City slug (milano, roma, berlin, etc)")
):
    # ---- validate URL
    if not url.startswith("https://dice.fm/"):
        raise HTTPException(400, "Invalid DICE URL")

    # ---- city lookup
    city_res = supabase.table("cities") \
        .select("id") \
        .eq("slug", city_slug) \
        .single() \
        .execute()

    if not city_res.data:
        raise HTTPException(400, f"City '{city_slug}' not found")

    city_id = city_res.data["id"]

    # ---- infer category
    category_slug = infer_category_slug_from_dice_url(url)

    cat_res = supabase.table("categories") \
        .select("id") \
        .eq("slug", category_slug) \
        .eq("type", "event") \
        .single() \
        .execute()

    category_id = cat_res.data["id"] if cat_res.data else None

    # ---- fetch page
    try:
        res = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=20
        )
        res.raise_for_status()
        html = res.text
    except Exception as e:
        raise HTTPException(500, f"Failed to fetch DICE page: {e}")

    # ---- parse events
    events = extract_dice_events_from_html(html)

    inserted = 0
    skipped = 0

    for e in events:
        # dedup by source_url
        exists = supabase.table("submissions") \
            .select("id") \
            .eq("source_url", e["source_url"]) \
            .execute()

        if exists.data:
            skipped += 1
            continue

        description_parts = [
            e.get("venue_name"),
            e.get("date_text"),
            e.get("price_text"),
        ]

        description = " · ".join([p for p in description_parts if p])

        supabase.table("submissions").insert({
            "city_id": city_id,
            "source": "scraper:dice",
            "source_url": e["source_url"],
            "title": e["title"],
            "description": description,
            "image": e["image"],
            "category_id": category_id,
            "lat": None,
            "lng": None,
            "confidence": 55,
            "status": "draft",
        }).execute()

        inserted += 1

    return {
        "source": "dice",
        "city": city_slug,
        "url": url,
        "category": category_slug,
        "found": len(events),
        "inserted": inserted,
        "skipped": skipped,
    }
