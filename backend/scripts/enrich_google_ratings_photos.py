#!/usr/bin/env python3
"""
Soleia - Enrichissement RATINGS + PHOTOS via Google Places API (New).

Foursquare est en quota épuisé → on bascule sur Google Places (la même API
qu'on utilise déjà dans enrich_details.py / seed_cities.py).

Pour les terrasses sans note ou avec photo Unsplash placeholder :
  1. Si `google_place_id` existe : GET /places/{id} pour rating + photos
  2. Sinon : POST /places:searchText (textQuery="<name> <city>",
     locationBias circle 100m) pour trouver le place_id
  3. Stocke `google_rating`, `google_ratings_count`, `google_place_id`,
     `photo_url`, `photos[]`, `google_maps_uri`.

Usage:
    python3 scripts/enrich_google_ratings_photos.py [--cities Paris,Lyon] [--limit N] [--dry-run]
"""
from __future__ import annotations

import os
import sys
import time
import json
import asyncio
import argparse
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
load_dotenv(BACKEND_DIR / ".env")

GOOGLE_KEY = os.environ.get("GOOGLE_PLACES_API_KEY", "").strip()
if not GOOGLE_KEY:
    print("[ERR] GOOGLE_PLACES_API_KEY missing in .env", file=sys.stderr)
    sys.exit(1)

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ.get("DB_NAME", "soleia")

PLACE_DETAILS_URL = "https://places.googleapis.com/v1/places/{place_id}"
PLACE_SEARCH_URL  = "https://places.googleapis.com/v1/places:searchText"
PLACE_PHOTO_URL   = "https://places.googleapis.com/v1/{photo_name}/media?maxWidthPx=600&key=" + GOOGLE_KEY

DETAILS_FIELDS = ",".join([
    "id", "displayName", "rating", "userRatingCount",
    "googleMapsUri", "photos", "location",
])
SEARCH_FIELDS = ",".join([
    "places.id", "places.displayName", "places.rating",
    "places.userRatingCount", "places.googleMapsUri",
    "places.photos", "places.location",
])

DEFAULT_PHOTO_PATTERN = "unsplash"


async def google_get_details(client: httpx.AsyncClient, place_id: str) -> Optional[Dict[str, Any]]:
    try:
        r = await client.get(
            PLACE_DETAILS_URL.format(place_id=place_id),
            headers={"X-Goog-Api-Key": GOOGLE_KEY, "X-Goog-FieldMask": DETAILS_FIELDS},
            timeout=12,
        )
        if r.status_code == 404:
            return None
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None


async def google_search_one(client: httpx.AsyncClient, name: str, city: str,
                             lat: float, lng: float, radius_m: float = 200) -> Optional[Dict[str, Any]]:
    try:
        r = await client.post(
            PLACE_SEARCH_URL,
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": GOOGLE_KEY,
                "X-Goog-FieldMask": SEARCH_FIELDS,
            },
            json={
                "textQuery": f"{name} {city}",
                "maxResultCount": 1,
                "locationBias": {
                    "circle": {
                        "center": {"latitude": lat, "longitude": lng},
                        "radius": radius_m,
                    }
                },
            },
            timeout=12,
        )
        if r.status_code != 200:
            return None
        places = (r.json() or {}).get("places") or []
        return places[0] if places else None
    except Exception:
        return None


async def run(cities: List[str], limit: Optional[int], dry_run: bool):
    client_db = AsyncIOMotorClient(MONGO_URL)
    db = client_db[DB_NAME]
    coll = db.terraces

    query = {
        "city": {"$in": cities},
        "$or": [
            {"google_rating": None},
            {"google_rating": {"$exists": False}},
            {"google_rating": 0},
            {"photo_url": {"$regex": DEFAULT_PHOTO_PATTERN}},
            {"photo_url": None},
            {"photo_url": {"$exists": False}},
        ],
    }
    pipeline = [
        {"$match": query},
        {"$addFields": {
            "_p_conf": {"$cond": [{"$eq": ["$has_terrace_confirmed", True]}, 0, 1]},
        }},
        {"$sort": {"_p_conf": 1}},
    ]
    if limit:
        pipeline.append({"$limit": int(limit)})
    pipeline.append({"$project": {
        "id": 1, "name": 1, "city": 1, "lat": 1, "lng": 1,
        "google_rating": 1, "google_place_id": 1, "photo_url": 1, "_id": 0,
    }})
    docs = await coll.aggregate(pipeline, allowDiskUse=True).to_list(length=None)
    print(f"[ENRICH GOOGLE] {len(docs)} terrasses (cities={cities}, limit={limit})")

    by_city = {c: {"updated": 0, "rating": 0, "photo": 0, "no_match": 0, "skipped": 0} for c in cities}

    async with httpx.AsyncClient() as http:
        for i, t in enumerate(docs, 1):
            city = t.get("city") or "?"
            bc = by_city.setdefault(city, {"updated": 0, "rating": 0, "photo": 0, "no_match": 0, "skipped": 0})
            place_id = t.get("google_place_id")
            place: Optional[Dict[str, Any]] = None

            if place_id:
                place = await google_get_details(http, place_id)
            if not place:
                try:
                    place = await google_search_one(http, t["name"], city, float(t["lat"]), float(t["lng"]))
                except (KeyError, TypeError, ValueError):
                    place = None
                if place:
                    place_id = place.get("id")

            if not place:
                bc["no_match"] += 1
                continue

            update: Dict[str, Any] = {}

            new_rating = place.get("rating")
            cur_rating = t.get("google_rating") or 0
            if isinstance(new_rating, (int, float)) and new_rating > 0 and not cur_rating:
                update["google_rating"] = float(new_rating)
                update["google_ratings_count"] = int(place.get("userRatingCount") or 0)
                bc["rating"] += 1

            current_photo = t.get("photo_url") or ""
            if (DEFAULT_PHOTO_PATTERN in current_photo) or not current_photo:
                photos = place.get("photos") or []
                if photos:
                    pname = photos[0].get("name")
                    if pname:
                        photo_url = PLACE_PHOTO_URL.format(photo_name=pname)
                        update["photo_url"] = photo_url
                        update["photos"] = [photo_url]
                        bc["photo"] += 1

            if place_id and not t.get("google_place_id"):
                update["google_place_id"] = place_id
            maps_uri = place.get("googleMapsUri")
            if maps_uri:
                update["google_maps_uri"] = maps_uri

            if not update:
                bc["skipped"] += 1
            else:
                if not dry_run:
                    await coll.update_one({"id": t["id"]}, {"$set": update})
                bc["updated"] += 1

            if i % 50 == 0 or i == 1:
                print(f"  [{i}/{len(docs)}] {city} · {(t.get('name') or '')[:35]} → keys={list(update.keys())}")
            await asyncio.sleep(0.10)  # ~10 req/s — Google Places ok

    print("\n=== ENRICH GOOGLE DONE ===")
    for c, s in by_city.items():
        if any(s.values()):
            print(f"  {c:<11} updated={s['updated']:<5} rating+={s['rating']:<5} photo+={s['photo']:<5} no_match={s['no_match']:<5} skipped={s['skipped']}")
    log = SCRIPT_DIR / "enrich_google_ratings_photos_last_run.json"
    log.write_text(json.dumps(by_city, indent=2, ensure_ascii=False))
    print(f"\n[LOG] {log}")
    client_db.close()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--cities", default="Paris,Lyon,Marseille,Nantes")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    cities = [c.strip() for c in args.cities.split(",") if c.strip()]
    asyncio.run(run(cities, args.limit, args.dry_run))


if __name__ == "__main__":
    main()
