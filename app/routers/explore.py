from fastapi import APIRouter, HTTPException
from datetime import datetime, timezone
from typing import Optional

from app.core.database import supabase
from app.routers.home import get_price_level, unique_by_id  # 👈 riuso helpers

router = APIRouter(
    prefix="/explore",
    tags=["explore"],
)

@router.get("/limited")
def limited_explore(
    city_slug: str,
    type: Optional[str] = "mixed",  # event | place | mixed
    price: Optional[int] = None,
    district: Optional[str] = None,
):
    try:
        city = (
            supabase.table("cities")
            .select("id")
            .eq("slug", city_slug)
            .single()
            .execute()
            .data
        )

        city_id = city["id"]
        now_utc = datetime.now(timezone.utc)

        used_ids = set()
        results = []

        # =============================
        # EVENTS (max 5)
        # =============================
        if type in ("event", "mixed"):
            events_q = (
                supabase.table("events")
                .select("""
                    id,
                    title,
                    cover_image,
                    start_at,
                    lat,
                    lng,
                    source_url,
                    price_min,
                    price_max,
                    categories(name)
                """)
                .eq("city_id", city_id)
                .gte("start_at", now_utc.isoformat())
                .order("start_at")
                .limit(20)
            )

            events_raw = events_q.execute().data or []

            events = [
                {
                    "id": e["id"],
                    "title": e["title"],
                    "imageUrl": e["cover_image"],
                    "source_url": e["source_url"],
                    "category": e["categories"]["name"] if e.get("categories") else "Event",
                    "time": e["start_at"],
                    "priceLevel": get_price_level(e.get("price_min"), e.get("price_max")),
                    "type": "event",
                }
                for e in events_raw
            ]

            if price:
                events = [e for e in events if e["priceLevel"] == price]

            results += unique_by_id(events, used_ids, limit=5)

        # =============================
        # PLACES (max 5)
        # =============================
        if type in ("place", "mixed"):
            places_q = (
                supabase.table("places")
                .select("""
                    id,
                    name,
                    cover_image,
                    address,
                    price_level,
                    categories(name)
                """)
                .eq("city_id", city_id)
                .limit(20)
            )

            places_raw = places_q.execute().data or []

            places = [
                {
                    "id": p["id"],
                    "title": p["name"],
                    "imageUrl": p["cover_image"],
                    "address": p["address"],
                    "priceLevel": p.get("price_level"),
                    "category": p["categories"]["name"] if p.get("categories") else "Place",
                    "type": "place",
                }
                for p in places_raw
            ]

            if price:
                places = [p for p in places if p["priceLevel"] == price]

            results += unique_by_id(places, used_ids, limit=5)

        return {
            "items": results[:10]
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/search")
def explore_search(
    city_slug: str,
    type: str = "mixed",  # event | place | mixed
    price: Optional[int] = None,
    district: Optional[str] = None,  # neighborhood slug
):
    try:
        # =====================
        # CITY
        # =====================
        city = (
            supabase.table("cities")
            .select("id")
            .eq("slug", city_slug)
            .single()
            .execute()
            .data
        )

        if not city:
            raise HTTPException(status_code=404, detail="City not found")

        city_id = city["id"]
        now = datetime.now(timezone.utc)

        events: list = []
        places: list = []

        # =====================
        # EVENTS (NO DISTRICT)
        # =====================
        if type in ("event", "mixed"):
            q = (
                supabase.table("events")
                .select("""
                    id,
                    title,
                    cover_image,
                    start_at,
                    price_min,
                    price_max,
                    categories(name)
                """)
                .eq("city_id", city_id)
                .gte("start_at", now.isoformat())
                .order("start_at")
                .limit(20)
            )

            events_raw = q.execute().data or []

            events = [
                {
                    "id": e["id"],
                    "title": e["title"],
                    "imageUrl": e["cover_image"],
                    "time": e["start_at"],
                    "priceLevel": get_price_level(
                        e.get("price_min"),
                        e.get("price_max"),
                    ),
                    "category": e["categories"]["name"]
                        if e.get("categories")
                        else "Event",
                    "type": "event",
                }
                for e in events_raw
                if not price
                or get_price_level(
                    e.get("price_min"),
                    e.get("price_max"),
                ) == price
            ]

        # =====================
        # PLACES (WITH DISTRICT)
        # =====================
        place_ids_in_district: Optional[list] = None

        if district:
            neighborhood = (
                supabase.table("neighborhoods")
                .select("id")
                .eq("slug", district)
                .single()
                .execute()
                .data
            )

            if neighborhood:
                rels = (
                    supabase.table("place_neighborhoods")
                    .select("place_id")
                    .eq("neighborhood_id", neighborhood["id"])
                    .execute()
                    .data
                    or []
                )

                place_ids_in_district = [
                    r["place_id"] for r in rels
                ]

                # se il quartiere non ha luoghi → risposta vuota
                if not place_ids_in_district:
                    place_ids_in_district = []

        if type in ("place", "mixed"):
            q = (
                supabase.table("places")
                .select("""
                    id,
                    name,
                    cover_image,
                    address,
                    price_level,
                    categories(name),
                    place_neighborhoods(
                        neighborhoods(name)
                    )
                """)
                .eq("city_id", city_id)
                .limit(20)
            )

            if place_ids_in_district is not None:
                q = q.in_("id", place_ids_in_district)

            places_raw = q.execute().data or []

            places = [
                {
                    "id": p["id"],
                    "title": p["name"],
                    "imageUrl": p["cover_image"],
                    "address": p["address"],
                    "priceLevel": p.get("price_level"),
                    "category": p["categories"]["name"]
                        if p.get("categories")
                        else "Place",
                    "neighborhoods": [
                        n["neighborhoods"]["name"]
                        for n in p.get("place_neighborhoods", [])
                        if n.get("neighborhoods")
                    ],
                    "type": "place",
                }
                for p in places_raw
                if not price or p.get("price_level") == price
            ]

        # =====================
        # RESPONSE
        # =====================
        return {
            "events": events,
            "places": places,
        }

    except HTTPException:
        raise

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=str(e),
        )
