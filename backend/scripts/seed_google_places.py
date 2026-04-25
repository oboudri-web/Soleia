"""
Soleia - Seed complet via Google Places API (New) - searchNearby.

Remplace l'import OSM par Google Places pour les 11 villes hors Paris.
Découpage en grille (~12 zones/ville × 3 types = 36 appels par ville).

Run:
    cd /app/backend && python scripts/seed_google_places.py

ENV requis:
    MONGO_URL, DB_NAME, GOOGLE_PLACES_API_KEY
"""

from __future__ import annotations

import asyncio
import math
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
import pytz
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

try:
    from seed_data import orientation_label  # type: ignore
except Exception:
    def orientation_label(d):
        return str(int(d)) + "°"

GOOGLE_API_KEY = os.environ["GOOGLE_PLACES_API_KEY"]

# Places API (New)
SEARCH_NEARBY_URL = "https://places.googleapis.com/v1/places:searchNearby"

FIELD_MASK = ",".join(
    [
        "places.id",
        "places.displayName",
        "places.rating",
        "places.userRatingCount",
        "places.photos",
        "places.primaryTypeDisplayName",
        "places.types",
        "places.formattedAddress",
        "places.location",
        "places.googleMapsUri",
    ]
)

CITIES_CENTERS = [
    {"name": "Paris",       "center": (48.8566, 2.3522)},
    {"name": "Lyon",        "center": (45.7640, 4.8357)},
    {"name": "Marseille",   "center": (43.2965, 5.3698)},
    {"name": "Bordeaux",    "center": (44.8378, -0.5792)},
    {"name": "Nantes",      "center": (47.2184, -1.5536)},
    {"name": "Toulouse",    "center": (43.6047, 1.4442)},
    {"name": "Nice",        "center": (43.7102, 7.2620)},
    {"name": "Montpellier", "center": (43.6108, 3.8767)},
]


def generate_dense_grid(center_lat: float, center_lng: float, n: int = 7, step_m: int = 500) -> list[tuple[float, float]]:
    """
    Grille dense n×n centrée sur (center_lat, center_lng) avec pas step_m.
    """
    import math as _m
    step_lat = step_m / 111000.0
    step_lng = step_m / (111000.0 * max(0.1, _m.cos(_m.radians(center_lat))))
    half = (n - 1) / 2
    zones: list[tuple[float, float]] = []
    for i in range(n):
        for j in range(n):
            lat = center_lat + (i - half) * step_lat
            lng = center_lng + (j - half) * step_lng
            zones.append((lat, lng))
    return zones


# Grille dense 13×13 = 169 zones par ville (cible 150±), step 300m → couverture ~4km de rayon
CITIES = [
    {**c, "grid": generate_dense_grid(c["center"][0], c["center"][1], n=13, step_m=300)}
    for c in CITIES_CENTERS
]

# Places API (New) types - https://developers.google.com/maps/documentation/places/web-service/place-types
INCLUDED_TYPES = ["bar", "cafe", "restaurant"]


async def search_nearby(lat: float, lng: float, types: list[str], client: httpx.AsyncClient, radius: int = 350) -> list[dict]:
    try:
        resp = await client.post(
            SEARCH_NEARBY_URL,
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": GOOGLE_API_KEY,
                "X-Goog-FieldMask": FIELD_MASK,
            },
            json={
                "includedTypes": types,
                "maxResultCount": 20,
                "locationRestriction": {
                    "circle": {
                        "center": {"latitude": lat, "longitude": lng},
                        "radius": radius,
                    }
                },
            },
            timeout=20,
        )
        if resp.status_code >= 400:
            print(f"    searchNearby {resp.status_code}: {resp.text[:200]}")
            return []
        return (resp.json() or {}).get("places") or []
    except Exception as e:
        print(f"    searchNearby error: {e}")
        return []


async def resolve_photo(photo_name: str, client: httpx.AsyncClient) -> Optional[str]:
    try:
        resp = await client.get(
            f"https://places.googleapis.com/v1/{photo_name}/media",
            params={"maxWidthPx": 600, "key": GOOGLE_API_KEY, "skipHttpRedirect": "true"},
            timeout=15,
        )
        if resp.status_code != 200:
            return None
        return (resp.json() or {}).get("photoUri")
    except Exception:
        return None


def infer_type(place: dict) -> str:
    types = place.get("types") or []
    if "bar" in types:
        return "bar"
    if "cafe" in types or "coffee_shop" in types:
        return "cafe"
    if "restaurant" in types:
        return "restaurant"
    # Fallback sur primaryType
    primary = (place.get("primaryTypeDisplayName") or {}).get("text", "").lower()
    if "bar" in primary:
        return "bar"
    if "café" in primary or "cafe" in primary or "coffee" in primary:
        return "cafe"
    return "restaurant"


def fallback_photo(amenity: str) -> str:
    base = {
        "bar": "https://images.unsplash.com/photo-1551024709-8f23befc6f87",
        "cafe": "https://images.unsplash.com/photo-1445116572660-236099ec97a0",
        "restaurant": "https://images.unsplash.com/photo-1517248135467-4c7edcad34c4",
    }
    return f"{base.get(amenity, base['bar'])}?crop=entropy&cs=srgb&fm=jpg&w=800&q=85"


async def seed_city(city: dict, db, upsert_mode: bool = False):
    print(f"\nImport {city['name']}... (mode={'UPSERT' if upsert_mode else 'DELETE+INSERT'})")

    preserved_pids: set[str] = set()

    if not upsert_mode:
        # Legacy mode : on préserve manual + confirmed, on supprime le reste, puis on insère.
        preserve_filter = {
            "city": city["name"],
            "$or": [
                {"terrace_source": "manual"},
                {"has_terrace_confirmed": True},
            ],
        }
        preserved = await db.terraces.count_documents(preserve_filter)
        cursor = db.terraces.find(preserve_filter, {"google_place_id": 1, "_id": 0})
        preserved_pids = {d.get("google_place_id") for d in await cursor.to_list(10000) if d.get("google_place_id")}
        print(f"  {preserved} terrasses preservees (manuelles + deja confirmees)")

        # Supprimer le reste de la ville (non-preserves)
        await db.terraces.delete_many({
            "city": city["name"],
            "$and": [
                {"terrace_source": {"$ne": "manual"}},
                {"$or": [
                    {"has_terrace_confirmed": {"$ne": True}},
                    {"has_terrace_confirmed": {"$exists": False}},
                ]},
            ],
        })
    else:
        # UPSERT mode : ZERO DELETE. On match sur google_place_id, on préserve tous les enrichissements.
        total_existing = await db.terraces.count_documents({"city": city["name"]})
        print(f"  {total_existing} terrasses existantes preservees (zero delete, mode UPSERT)")

    all_places: dict[str, dict] = {}

    async with httpx.AsyncClient(timeout=20) as client:
        for (lat, lng) in city["grid"]:
            places = await search_nearby(lat, lng, INCLUDED_TYPES, client)
            for p in places:
                pid = p.get("id")
                if pid and pid not in all_places:
                    all_places[pid] = p
            await asyncio.sleep(0.1)

    print(f"  {len(all_places)} etablissements uniques")

    if not all_places:
        return 0

    center_lat, center_lng = city["center"]
    to_insert = []
    upsert_stats = {"inserted": 0, "updated": 0, "untouched": 0}
    for pid, place in all_places.items():
        loc = place.get("location") or {}
        lat = loc.get("latitude")
        lng = loc.get("longitude")
        if lat is None or lng is None:
            continue

        name = (place.get("displayName") or {}).get("text") or ""
        if not name:
            continue

        ttype = infer_type(place)

        # Pendant le seed dense on ne résout PAS les photos (massif coût).
        # On stocke le photoName pour résolution ultérieure après qualification.
        photos = place.get("photos") or []
        first_photo_name = photos[0].get("name") if photos else None

        # Orientation : façade opposée du centre ville
        angle = math.degrees(math.atan2(lng - center_lng, lat - center_lat))
        orientation = int(round((angle + 180) % 360))

        if upsert_mode:
            # $set : seulement les champs Google à RAFRAICHIR (safe : ne touche pas enrichments)
            set_fields = {
                "name": name,
                "lat": lat,
                "lng": lng,
                "address": place.get("formattedAddress") or city["name"],
                "google_rating": place.get("rating") or 4.0,
                "google_ratings_count": place.get("userRatingCount", 0),
                "google_maps_uri": place.get("googleMapsUri"),
                "google_photo_name": first_photo_name,
            }
            # $setOnInsert : champs à créer seulement pour les NOUVEAUX docs
            set_on_insert = {
                "id": str(uuid.uuid4()),
                "orientation_degrees": float(orientation),
                "orientation_label": orientation_label(orientation),
                "type": ttype,
                "city": city["name"],
                "arrondissement": None,
                "photos": [],
                "photo_url": fallback_photo(ttype),
                "has_cover": False,
                "capacity_estimate": 40,
                "has_terrace_confirmed": False,
                "terrace_source": "google_places",
                "description_ia": None,
                "ai_description": None,
                "created_at": datetime.now(pytz.utc),
                "google_place_id": pid,
            }
            result = await db.terraces.update_one(
                {"google_place_id": pid},
                {"$set": set_fields, "$setOnInsert": set_on_insert},
                upsert=True,
            )
            if result.upserted_id is not None:
                upsert_stats["inserted"] += 1
            elif result.modified_count:
                upsert_stats["updated"] += 1
            else:
                upsert_stats["untouched"] += 1
        else:
            to_insert.append({
                "id": str(uuid.uuid4()),
                "name": name,
                "lat": lat,
                "lng": lng,
                "orientation_degrees": float(orientation),
                "orientation_label": orientation_label(orientation),
                "type": ttype,
                "city": city["name"],
                "arrondissement": None,
                "address": place.get("formattedAddress") or city["name"],
                "google_rating": place.get("rating") or 4.0,
                "google_ratings_count": place.get("userRatingCount", 0),
                "google_place_id": pid,
                "google_maps_uri": place.get("googleMapsUri"),
                "google_photo_name": first_photo_name,
                "photos": [],
                "photo_url": fallback_photo(ttype),
                "has_cover": False,
                "capacity_estimate": 40,
                "has_terrace_confirmed": False,
                "terrace_source": "google_places",
                "description_ia": None,
                "ai_description": None,
                "created_at": datetime.now(pytz.utc),
            })

    if upsert_mode:
        print(f"  UPSERT done: +{upsert_stats['inserted']} nouveaux, ~{upsert_stats['updated']} rafraichis, ={upsert_stats['untouched']} inchanges")
        return upsert_stats["inserted"]

    # Filtrer les place_id déjà présents (préservés)
    if preserved_pids:
        before = len(to_insert)
        to_insert = [t for t in to_insert if t["google_place_id"] not in preserved_pids]
        print(f"  {before - len(to_insert)} doublons avec etabs preservees supprimes")

    if to_insert:
        await db.terraces.insert_many(to_insert)
        print(f"  OK {len(to_insert)} inseres")
    return len(to_insert)


async def ensure_indexes(db):
    await db.terraces.create_index([("city", 1), ("has_terrace_confirmed", 1)])
    await db.terraces.create_index([("city", 1), ("lat", 1), ("lng", 1)])
    await db.terraces.create_index([("city", 1), ("type", 1), ("has_terrace_confirmed", 1)])
    await db.terraces.create_index([("google_place_id", 1)], sparse=True)
    await db.terraces.create_index([("terrace_source", 1)])


async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--city", default=None, help="Limit seed to a single city name (e.g. 'Paris').")
    parser.add_argument("--grid", type=int, default=13, help="Grid dimension N (N x N zones). Default 13 => 169 zones.")
    parser.add_argument("--step", type=int, default=300, help="Grid step in meters. Default 300.")
    parser.add_argument("--upsert", action="store_true", help="UPSERT mode: zero DELETE, match on google_place_id, preserve all enrichments.")
    args = parser.parse_args()

    # Rebuild CITIES list with custom grid size if requested
    cities_config = CITIES_CENTERS
    if args.city:
        cities_config = [c for c in CITIES_CENTERS if c["name"].lower() == args.city.lower()]
        if not cities_config:
            print(f"Unknown city '{args.city}'. Available: {[c['name'] for c in CITIES_CENTERS]}")
            return

    cities = [
        {**c, "grid": generate_dense_grid(c["center"][0], c["center"][1], n=args.grid, step_m=args.step)}
        for c in cities_config
    ]
    mode_label = "UPSERT" if args.upsert else "DELETE+INSERT"
    print(f"Seeding {len(cities)} city/cities with a {args.grid}x{args.grid} grid ({args.grid * args.grid} zones) step {args.step}m | mode={mode_label}")

    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ.get("DB_NAME", "suntterrace_db")]
    await ensure_indexes(db)

    total = 0
    for city in cities:
        n = await seed_city(city, db, upsert_mode=args.upsert)
        total += n
        print(f"  Progression: {total} etablissements total")
        await asyncio.sleep(1)

    print(f"\nTermine. {total} etablissements importes.")
    client.close()


if __name__ == "__main__":
    asyncio.run(main())
