#!/usr/bin/env python3
"""
Soleia - Enrichissement RATINGS + PHOTOS via Foursquare Service API v2025.

Pour les terrasses sans note Google ou avec photo Unsplash placeholder :
  - Si `foursquare_fsq_id` existe : GET /places/{id} pour rating + /photos pour photo
  - Sinon : /places/search par nom + bbox 100m pour trouver le match → idem
  - Met à jour `google_rating`, `google_ratings_count`, `photo_url`, `photos`,
    `foursquare_fsq_id` (nouvellement renseigné).

Usage:
    python3 scripts/enrich_fsq_ratings_photos.py [--cities Paris,Lyon] [--limit N] [--dry-run]
"""
from __future__ import annotations

import os
import sys
import time
import json
import argparse
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv
from pymongo import MongoClient

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
load_dotenv(BACKEND_DIR / ".env")

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ.get("DB_NAME", "soleia")
db = MongoClient(MONGO_URL)[DB_NAME]
terraces = db.terraces

FSQ_KEY = os.environ.get("FOURSQUARE_API_KEY", "").strip()
if not FSQ_KEY:
    print("[ERR] FOURSQUARE_API_KEY missing", file=sys.stderr)
    sys.exit(1)

FSQ_BASE = "https://places-api.foursquare.com"
session = requests.Session()
session.headers.update({
    "Accept": "application/json",
    "Authorization": f"Bearer {FSQ_KEY}",
    "X-Places-Api-Version": "2025-06-17",
})

DEFAULT_PHOTO_PATTERN = "unsplash"


def fsq_get_place(fsq_id: str) -> Optional[Dict[str, Any]]:
    """GET /places/{fsq_id} — returns rating + stats + categories."""
    try:
        r = session.get(f"{FSQ_BASE}/places/{fsq_id}", timeout=12)
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None


def fsq_get_photos(fsq_id: str, limit: int = 4) -> List[str]:
    try:
        r = session.get(f"{FSQ_BASE}/places/{fsq_id}/photos",
                        params={"limit": limit}, timeout=10)
        if r.status_code != 200:
            return []
        return [f"{p.get('prefix','')}original{p.get('suffix','')}"
                for p in (r.json() or []) if p.get("prefix") and p.get("suffix")]
    except Exception:
        return []


def fsq_search_one(name: str, lat: float, lng: float) -> Optional[Dict[str, Any]]:
    """Find best FSQ match for (name, lat, lng) within 75m."""
    try:
        params = {
            "query": name,
            "ll": f"{lat},{lng}",
            "radius": 100,
            "limit": 3,
            "sort": "DISTANCE",
        }
        r = session.get(f"{FSQ_BASE}/places/search", params=params, timeout=12)
        if r.status_code != 200:
            return None
        results = (r.json() or {}).get("results") or []
        if not results:
            return None
        return results[0]
    except Exception:
        return None


def run(cities: List[str], limit: Optional[int], dry_run: bool):
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
    cursor = terraces.find(query, {
        "id": 1, "name": 1, "city": 1, "lat": 1, "lng": 1,
        "google_rating": 1, "google_ratings_count": 1,
        "photo_url": 1, "foursquare_fsq_id": 1, "_id": 0,
    })
    docs = list(cursor)
    if limit:
        docs = docs[:int(limit)]
    print(f"[ENRICH FSQ] {len(docs)} terrasses à enrichir (cities={cities}, limit={limit})")

    by_city: Dict[str, Dict[str, int]] = {c: {"updated": 0, "skipped": 0, "rating_only": 0,
                                              "photo_only": 0, "both": 0, "no_match": 0} for c in cities}

    for i, t in enumerate(docs, 1):
        city = t.get("city") or "?"
        bcity = by_city.setdefault(city, {"updated": 0, "skipped": 0, "rating_only": 0,
                                          "photo_only": 0, "both": 0, "no_match": 0})
        fsq_id = t.get("foursquare_fsq_id")
        place: Optional[Dict[str, Any]] = None

        if fsq_id:
            place = fsq_get_place(fsq_id)
        if not place:
            try:
                place = fsq_search_one(t["name"], float(t["lat"]), float(t["lng"]))
            except (KeyError, TypeError, ValueError):
                place = None
            if place:
                fsq_id = place.get("fsq_place_id") or place.get("fsq_id")
        if not place:
            bcity["no_match"] += 1
            continue

        # Build update doc with whatever signals FSQ gave us
        update: Dict[str, Any] = {}

        # rating (FSQ returns /10 → convert /5)
        raw_rating = place.get("rating")
        if isinstance(raw_rating, (int, float)) and raw_rating > 0:
            new_rating = round(raw_rating / 2.0, 1)
            cur_rating = t.get("google_rating") or 0
            if cur_rating in (None, 0):
                update["google_rating"] = new_rating
                stats = place.get("stats") or {}
                update["google_ratings_count"] = int(
                    stats.get("total_ratings") or stats.get("total_tips") or 0
                )

        # photos (only if current is unsplash placeholder or missing)
        current_photo = t.get("photo_url") or ""
        if (DEFAULT_PHOTO_PATTERN in current_photo) or not current_photo:
            if fsq_id:
                photos = fsq_get_photos(fsq_id)
                if photos:
                    update["photo_url"] = photos[0]
                    update["photos"] = photos

        if fsq_id and not t.get("foursquare_fsq_id"):
            update["foursquare_fsq_id"] = fsq_id

        if not update:
            bcity["skipped"] += 1
        else:
            if not dry_run:
                terraces.update_one({"id": t["id"]}, {"$set": update})
            bcity["updated"] += 1
            has_rating = "google_rating" in update
            has_photo  = "photo_url" in update
            if has_rating and has_photo:
                bcity["both"] += 1
            elif has_rating:
                bcity["rating_only"] += 1
            elif has_photo:
                bcity["photo_only"] += 1

        if i % 50 == 0 or i == 1:
            print(f"  [{i}/{len(docs)}] {city} · {(t.get('name') or '')[:40]} → keys={list(update.keys())}")
        # FSQ rate-limit (50 req/s upper bound, we stay safe)
        time.sleep(0.18)

    print("\n=== ENRICH FSQ DONE ===")
    for c, s in by_city.items():
        if any(s.values()):
            print(f"  {c:<11} updated={s['updated']} (both={s['both']} rating_only={s['rating_only']} "
                  f"photo_only={s['photo_only']}) | skipped={s['skipped']} no_match={s['no_match']}")
    log = SCRIPT_DIR / "enrich_fsq_ratings_photos_last_run.json"
    log.write_text(json.dumps(by_city, indent=2, ensure_ascii=False))
    print(f"\n[LOG] {log}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--cities", default="Paris,Lyon,Marseille,Nantes")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    cities = [c.strip() for c in args.cities.split(",") if c.strip()]
    run(cities, args.limit, args.dry_run)


if __name__ == "__main__":
    main()
