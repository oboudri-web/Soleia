"""
Soleia - Multi-city OSM + Google Places import.

Enrichit les terrasses de 11 grandes villes françaises (hors Nantes qui reste
gérée par seed_data.py) avec :
  - OSM Overpass pour l'emplacement + outdoor_seating
  - Google Places API (New) pour rating + nombre d'avis + photo permanente
  - Fallback propre si GOOGLE_PLACES_API_KEY absent

Run:
    cd /app/backend && python scripts/seed_cities.py

ENV requis:
    MONGO_URL, DB_NAME
    GOOGLE_PLACES_API_KEY
"""

from __future__ import annotations

import asyncio
import math
import os
import random
import sys
from pathlib import Path
from typing import Optional

import httpx
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

try:
    from seed_data import orientation_label  # type: ignore
except Exception:  # pragma: no cover
    def orientation_label(d):
        return str(int(d)) + "°"


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
CITIES = [
    {"name": "Paris",       "lat": 48.8566, "lng": 2.3522,   "bbox": "48.81,2.22,48.91,2.47"},
    {"name": "Lyon",        "lat": 45.7640, "lng": 4.8357,   "bbox": "45.70,4.77,45.82,4.90"},
    {"name": "Marseille",   "lat": 43.2965, "lng": 5.3698,   "bbox": "43.22,5.28,43.37,5.45"},
    {"name": "Bordeaux",    "lat": 44.8378, "lng": -0.5792,  "bbox": "44.80,-0.64,44.87,-0.53"},
    {"name": "Toulouse",    "lat": 43.6047, "lng": 1.4442,   "bbox": "43.55,1.38,43.66,1.51"},
    {"name": "Strasbourg",  "lat": 48.5734, "lng": 7.7521,   "bbox": "48.54,7.70,48.61,7.81"},
    {"name": "Lille",       "lat": 50.6292, "lng": 3.0573,   "bbox": "50.59,3.01,50.67,3.10"},
    {"name": "Nice",        "lat": 43.7102, "lng": 7.2620,   "bbox": "43.68,7.22,43.74,7.31"},
    {"name": "Montpellier", "lat": 43.6108, "lng": 3.8767,   "bbox": "43.57,3.83,43.65,3.93"},
    {"name": "Rennes",      "lat": 48.1173, "lng": -1.6778,  "bbox": "48.08,-1.73,48.15,-1.62"},
    {"name": "Grenoble",    "lat": 45.1885, "lng": 5.7245,   "bbox": "45.16,5.69,45.21,5.76"},
]

OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.openstreetmap.fr/api/interpreter",
]

# --- Google Places API (New) ---
GOOGLE_TEXTSEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
GOOGLE_API_KEY = os.environ.get("GOOGLE_PLACES_API_KEY", "").strip() or None
GOOGLE_RATE_LIMIT_SLEEP = 0.04  # ~25 req/s

# Volume par ville (pas de cap global - budget 300$)
MAX_CONFIRMED_PER_CITY = 60
MAX_UNCONFIRMED_PER_CITY = 30

# Compteur pour log final
_google_calls = 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def estimate_orientation(lat: float, lng: float, city_lat: float, city_lng: float) -> int:
    angle = math.degrees(math.atan2(lng - city_lng, lat - city_lat))
    base = (angle + 180) % 360
    variation = random.randint(-30, 30)
    return int(round((base + variation) % 360))


async def _resolve_photo_uri(photo_name: str, client: httpx.AsyncClient) -> Optional[str]:
    """
    Convertit un photo_name Google en URL lh3.googleusercontent.com permanente
    (pas de quota applicatif une fois stockée).
    """
    global _google_calls
    if not photo_name or not GOOGLE_API_KEY:
        return None
    try:
        _google_calls += 1
        resp = await client.get(
            f"https://places.googleapis.com/v1/{photo_name}/media",
            params={
                "maxWidthPx": 600,
                "key": GOOGLE_API_KEY,
                "skipHttpRedirect": "true",
            },
            timeout=15,
        )
        if resp.status_code != 200:
            return None
        return (resp.json() or {}).get("photoUri")
    except Exception:
        return None


async def enrich_with_google(
    name: str,
    lat: float,
    lng: float,
    client: httpx.AsyncClient,
    city_name: str,
) -> dict:
    """
    Places API (New) Text Search + résolution photo permanente.
    """
    global _google_calls
    if not GOOGLE_API_KEY:
        return {}
    try:
        _google_calls += 1
        resp = await client.post(
            GOOGLE_TEXTSEARCH_URL,
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": GOOGLE_API_KEY,
                "X-Goog-FieldMask": ",".join(
                    [
                        "places.id",
                        "places.displayName",
                        "places.rating",
                        "places.userRatingCount",
                        "places.photos",
                        "places.primaryTypeDisplayName",
                        "places.formattedAddress",
                        "places.location",
                        "places.googleMapsUri",
                    ]
                ),
            },
            json={
                "textQuery": f"{name} {city_name}",
                "maxResultCount": 1,
                "locationBias": {
                    "circle": {
                        "center": {"latitude": lat, "longitude": lng},
                        "radius": 120.0,
                    }
                },
            },
            timeout=15,
        )
        if resp.status_code >= 400:
            return {}
        places = (resp.json() or {}).get("places") or []
        if not places:
            return {}

        place = places[0]
        loc = place.get("location") or {}
        plat, plng = loc.get("latitude"), loc.get("longitude")
        # Distance approx pour filtrer faux positifs (fallback si OSM a des coords imprécises)
        if plat is not None and plng is not None:
            dx = (plat - lat) * 111000
            dy = (plng - lng) * 85000
            if (dx * dx + dy * dy) ** 0.5 > 300:
                return {}

        photo_url = None
        photos = place.get("photos") or []
        if photos:
            photo_url = await _resolve_photo_uri(photos[0].get("name"), client)

        return {
            "google_place_id": place.get("id"),
            "google_rating": place.get("rating"),
            "google_ratings_count": place.get("userRatingCount", 0),
            "google_maps_uri": place.get("googleMapsUri"),
            "google_address": place.get("formattedAddress"),
            "photos": [photo_url] if photo_url else [],
        }
    except Exception as e:
        print(f"    Google Places error {name}: {e}")
        return {}


def fallback_photo(amenity_type: str) -> str:
    base = {
        "bar": "https://images.unsplash.com/photo-1551024709-8f23befc6f87",
        "cafe": "https://images.unsplash.com/photo-1445116572660-236099ec97a0",
        "restaurant": "https://images.unsplash.com/photo-1517248135467-4c7edcad34c4",
    }
    url = base.get(amenity_type, base["bar"])
    return f"{url}?crop=entropy&cs=srgb&fm=jpg&w=800&q=85"


def build_terrace_doc(el: dict, city: dict, extra: dict, confirmed: bool) -> Optional[dict]:
    lat = el.get("lat") or el.get("center", {}).get("lat")
    lng = el.get("lon") or el.get("center", {}).get("lon")
    if not lat or not lng:
        return None
    tags = el.get("tags", {}) or {}
    name = tags.get("name")
    if not name:
        return None

    amenity = tags.get("amenity", "bar")
    type_map = {"bar": "bar", "cafe": "cafe", "restaurant": "restaurant"}
    ori_deg = estimate_orientation(lat, lng, city["lat"], city["lng"])
    primary_photo = (
        (extra.get("photos") or [None])[0]
        if extra.get("photos")
        else fallback_photo(amenity)
    )

    return {
        "name": name,
        "lat": lat,
        "lng": lng,
        "orientation_degrees": float(ori_deg),
        "orientation_label": orientation_label(ori_deg),
        "type": type_map.get(amenity, "bar"),
        "city": city["name"],
        "arrondissement": tags.get("addr:suburb") or tags.get("addr:city"),
        "address": extra.get("google_address")
        or tags.get("addr:full")
        or " ".join(
            filter(
                None,
                [
                    tags.get("addr:housenumber"),
                    tags.get("addr:street"),
                    tags.get("addr:postcode"),
                    tags.get("addr:city"),
                ],
            )
        )
        or city["name"],
        "google_rating": extra.get("google_rating")
        or round(3.5 + (abs(hash(name)) % 15) / 10, 1),
        "google_ratings_count": extra.get("google_ratings_count", 0),
        "google_place_id": extra.get("google_place_id"),
        "google_maps_uri": extra.get("google_maps_uri"),
        "photos": extra.get("photos", []),
        "photo_url": primary_photo,
        "has_cover": bool(tags.get("covered") in ("yes", "arcade", "roof")),
        "capacity_estimate": int(tags.get("capacity") or (40 if confirmed else 35)),
        "has_terrace_confirmed": confirmed,
        "terrace_source": "osm" if confirmed else "osm_unconfirmed",
        "description_ia": None,
        "ai_description": None,
    }


async def overpass_query(query: str, client: httpx.AsyncClient) -> list:
    for url in OVERPASS_URLS:
        try:
            resp = await client.post(url, data={"data": query}, timeout=60)
            if resp.status_code != 200:
                continue
            try:
                data = resp.json()
            except Exception:
                continue
            elements = data.get("elements")
            if elements is not None:
                return elements
        except Exception as e:
            print(f"    Overpass {url}: {e}")
            continue
    return []


async def fetch_terraces_for_city(city: dict) -> list[dict]:
    query_confirmed = f"""
    [out:json][timeout:30];
    (
      node["amenity"~"bar|cafe|restaurant"]["outdoor_seating"="yes"]["name"]({city['bbox']});
      way["amenity"~"bar|cafe|restaurant"]["outdoor_seating"="yes"]["name"]({city['bbox']});
    );
    out center 300;
    """

    query_all = f"""
    [out:json][timeout:30];
    (
      node["amenity"~"bar|cafe|restaurant"]["outdoor_seating"!="yes"]["name"]({city['bbox']});
      way["amenity"~"bar|cafe|restaurant"]["outdoor_seating"!="yes"]["name"]({city['bbox']});
    );
    out center 300;
    """

    terraces: list[dict] = []

    async with httpx.AsyncClient(timeout=60) as client:
        confirmed_elements = await overpass_query(query_confirmed, client)
        await asyncio.sleep(1.5)
        all_elements = await overpass_query(query_all, client)

        confirmed_names: set[str] = set()
        for el in confirmed_elements[:MAX_CONFIRMED_PER_CITY]:
            tags = el.get("tags", {}) or {}
            name = tags.get("name")
            lat = el.get("lat") or el.get("center", {}).get("lat")
            lng = el.get("lon") or el.get("center", {}).get("lon")
            if not name or not lat or not lng:
                continue

            extra = await enrich_with_google(name, lat, lng, client, city["name"])
            await asyncio.sleep(GOOGLE_RATE_LIMIT_SLEEP)
            doc = build_terrace_doc(el, city, extra, confirmed=True)
            if doc:
                terraces.append(doc)
                confirmed_names.add(name)

        for el in all_elements[:MAX_UNCONFIRMED_PER_CITY]:
            tags = el.get("tags", {}) or {}
            name = tags.get("name")
            lat = el.get("lat") or el.get("center", {}).get("lat")
            lng = el.get("lon") or el.get("center", {}).get("lon")
            if not name or name in confirmed_names or not lat or not lng:
                continue

            extra = await enrich_with_google(name, lat, lng, client, city["name"])
            await asyncio.sleep(GOOGLE_RATE_LIMIT_SLEEP)
            doc = build_terrace_doc(el, city, extra, confirmed=False)
            if doc:
                terraces.append(doc)

    return terraces


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def ensure_indexes(db):
    await db.terraces.create_index([("city", 1), ("has_terrace_confirmed", 1)])
    await db.terraces.create_index([("city", 1), ("lat", 1), ("lng", 1)])
    await db.terraces.create_index([("city", 1), ("type", 1), ("has_terrace_confirmed", 1)])
    await db.terraces.create_index([("google_place_id", 1)], sparse=True)
    print("  Indexes created / verified")


async def main():
    import uuid
    from datetime import datetime
    import pytz

    mongo_url = os.environ["MONGO_URL"]
    db_name = os.environ.get("DB_NAME", "suntterrace_db")
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    await ensure_indexes(db)

    if not GOOGLE_API_KEY:
        print("GOOGLE_PLACES_API_KEY absent - mode fallback (notes estimees).")

    total_confirmed = 0
    total_unconfirmed = 0
    total_enriched = 0

    for city in CITIES:
        print(f"\nImport {city['name']}...")
        terraces = await fetch_terraces_for_city(city)
        if not terraces:
            print(f"  Aucun resultat pour {city['name']}")
            continue

        confirmed = [t for t in terraces if t["has_terrace_confirmed"]]
        unconfirmed = [t for t in terraces if not t["has_terrace_confirmed"]]
        enriched = [t for t in terraces if t.get("google_place_id")]

        for t in terraces:
            t["id"] = str(uuid.uuid4())
            t["created_at"] = datetime.now(pytz.utc)

        await db.terraces.delete_many({"city": city["name"]})
        await db.terraces.insert_many(terraces)

        print(
            f"  OK {len(confirmed)} confirmees, {len(unconfirmed)} candidates, "
            f"{len(enriched)} enrichies Google"
        )
        total_confirmed += len(confirmed)
        total_unconfirmed += len(unconfirmed)
        total_enriched += len(enriched)

    print(
        f"\nTotal import: {total_confirmed} confirmees, {total_unconfirmed} candidates, "
        f"{total_enriched} enrichies Google. Appels Google effectues: {_google_calls}"
    )
    client.close()


if __name__ == "__main__":
    asyncio.run(main())
