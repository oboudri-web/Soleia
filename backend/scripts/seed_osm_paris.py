"""
Soleia - OSM Overpass seed for Paris (Phase 1 of enrichment overnight).

Strategy (option B: ZERO écrasement):
- Query Overpass API for amenity=bar/cafe/restaurant in Paris bbox
- For each OSM result:
  - If a doc exists within 50m with a matching amenity type -> SKIP (preserve existing)
    and cross-reference the doc with osm_id for later use
  - Else -> INSERT new doc with terrace_source="osm"

Rate-limiting: 3 Overpass mirrors (primary/kumi/mail.ru) with backoff.

Run: python3 /app/backend/scripts/seed_osm_paris.py
"""
from __future__ import annotations
import asyncio
import math
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).parent.parent
load_dotenv(ROOT_DIR / ".env")

OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]

MATCH_RADIUS_M = 50  # Option B: skip if any existing doc within 50m

# Per-city bboxes (intra-muros + 1ère couronne when relevant)
CITY_BBOXES: dict[str, dict] = {
    "Paris":       {"south": 48.815, "west":  2.225, "north": 48.905, "east":  2.470},
    "Lyon":        {"south": 45.700, "west":  4.770, "north": 45.805, "east":  4.920},
    "Marseille":   {"south": 43.210, "west":  5.290, "north": 43.370, "east":  5.520},
    "Bordeaux":    {"south": 44.790, "west": -0.660, "north": 44.900, "east": -0.530},
    "Nantes":      {"south": 47.170, "west": -1.620, "north": 47.280, "east": -1.480},
    "Toulouse":    {"south": 43.550, "west":  1.370, "north": 43.660, "east":  1.500},
    "Nice":        {"south": 43.640, "west":  7.200, "north": 43.760, "east":  7.340},
    "Montpellier": {"south": 43.560, "west":  3.810, "north": 43.680, "east":  3.930},
}

CITY_CENTERS: dict[str, tuple[float, float]] = {
    "Paris":       (48.8566, 2.3522),
    "Lyon":        (45.7640, 4.8357),
    "Marseille":   (43.2965, 5.3698),
    "Bordeaux":    (44.8378, -0.5792),
    "Nantes":      (47.2184, -1.5536),
    "Toulouse":    (43.6047, 1.4442),
    "Nice":        (43.7102, 7.2620),
    "Montpellier": (43.6110, 3.8767),
}

# Overpass QL: fetch all bars/cafes/restaurants in bbox
def build_query(bbox: dict) -> str:
    return f"""
[out:json][timeout:180];
(
  node["amenity"="bar"]({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']});
  node["amenity"="cafe"]({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']});
  node["amenity"="restaurant"]({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']});
  node["amenity"="pub"]({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']});
);
out body;
""".strip()


AMENITY_TO_TYPE = {
    "bar": "bar",
    "pub": "bar",
    "cafe": "cafe",
    "restaurant": "restaurant",
}

BAD_NAME_PREFIXES = {
    # Fast-food / chaîne à filtrer (user-requested)
    "mcdonald", "burger king", "kfc", "quick", "five guys",
    "domino", "pizza hut", "subway",
    "paul", "brioche doree", "brioche dorée",
    # Other common chains
    "o'tacos", "mezzo di pasta", "class'croute", "class croute",
    # NOTE: Starbucks est EXPLICITEMENT conservé (demande user)
}


def is_fast_food(name: str, tags: dict) -> bool:
    lname = (name or "").lower().strip()
    if tags.get("amenity") == "fast_food":
        return True
    cuisine = (tags.get("cuisine") or "").lower()
    if "fast" in cuisine or cuisine in {"burger", "pizza_fastfood"}:
        return True
    # User explicitly wanted to KEEP Starbucks, so NOT filtering that.
    for bad in BAD_NAME_PREFIXES:
        if lname.startswith(bad):
            return True
    return False


def haversine_m(lat1, lng1, lat2, lng2) -> float:
    R = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


async def fetch_overpass(query: str) -> list[dict]:
    backoffs = [0, 3, 8, 20, 45]
    last_err = None
    headers = {
        "Content-Type": "text/plain; charset=utf-8",
        "User-Agent": "Soleia/1.0 (seed_osm_paris)",
    }
    async with httpx.AsyncClient(timeout=180) as client:
        for attempt, backoff in enumerate(backoffs):
            if backoff:
                await asyncio.sleep(backoff)
            for mirror in OVERPASS_MIRRORS:
                try:
                    # Send raw query body (not form-encoded) — Overpass expects that
                    resp = await client.post(mirror, content=query.encode("utf-8"), headers=headers)
                    if resp.status_code == 200:
                        data = resp.json()
                        return data.get("elements") or []
                    if resp.status_code == 429:
                        print(f"  [overpass attempt {attempt}] {mirror} -> 429, backing off")
                        last_err = "429"
                        break  # back off globally
                    print(f"  [overpass attempt {attempt}] {mirror} -> {resp.status_code}")
                    last_err = f"status {resp.status_code}"
                except Exception as e:
                    last_err = str(e)
                    print(f"  [overpass attempt {attempt}] {mirror} -> {e}")
    raise RuntimeError(f"Overpass exhausted all retries: {last_err}")


async def doc_exists_within(db, lat: float, lng: float, radius_m: float) -> bool:
    """Return True if at least one doc exists within `radius_m` of the given point."""
    # Rough bbox filter first (~50m ≈ 0.00045 deg)
    d_lat = radius_m / 111_000.0
    d_lng = radius_m / (111_000.0 * math.cos(math.radians(lat)))
    bbox_q = {
        "lat": {"$gte": lat - d_lat, "$lte": lat + d_lat},
        "lng": {"$gte": lng - d_lng, "$lte": lng + d_lng},
    }
    async for doc in db.terraces.find(bbox_q, {"lat": 1, "lng": 1, "_id": 0}):
        if haversine_m(lat, lng, doc.get("lat", 0), doc.get("lng", 0)) <= radius_m:
            return True
    return False


async def seed_city(db, city: str):
    bbox = CITY_BBOXES[city]
    center_lat, center_lng = CITY_CENTERS[city]

    before_total = await db.terraces.count_documents({"city": city})
    print(f"\n[OSM {city}] Start. Current {city} docs: {before_total}")

    # Pre-load all existing coords into memory for fast dedupe
    existing_pts: list[tuple[float, float]] = []
    async for doc in db.terraces.find({"city": city}, {"lat": 1, "lng": 1, "_id": 0}):
        if doc.get("lat") is not None and doc.get("lng") is not None:
            existing_pts.append((doc["lat"], doc["lng"]))
    print(f"[OSM {city}] Preloaded {len(existing_pts)} existing coords")

    def has_nearby(lat: float, lng: float) -> bool:
        d_lat = MATCH_RADIUS_M / 111_000.0
        d_lng = MATCH_RADIUS_M / (111_000.0 * math.cos(math.radians(lat)))
        for elat, elng in existing_pts:
            if abs(elat - lat) > d_lat or abs(elng - lng) > d_lng:
                continue
            if haversine_m(lat, lng, elat, elng) <= MATCH_RADIUS_M:
                return True
        return False

    query = build_query(bbox)
    t0 = time.time()
    elements = await fetch_overpass(query)
    print(f"[OSM {city}] Overpass returned {len(elements)} elements in {time.time()-t0:.1f}s")

    stats = {
        "inserted": 0,
        "skipped_dedupe": 0,
        "skipped_fast_food": 0,
        "skipped_no_name": 0,
        "skipped_no_coords": 0,
    }

    batch: list[dict] = []
    for el in elements:
        if el.get("type") != "node":
            continue
        lat = el.get("lat")
        lng = el.get("lon")
        if lat is None or lng is None:
            stats["skipped_no_coords"] += 1
            continue
        tags = el.get("tags") or {}
        name = tags.get("name") or tags.get("name:fr") or ""
        if not name.strip():
            stats["skipped_no_name"] += 1
            continue
        amenity = tags.get("amenity")
        ttype = AMENITY_TO_TYPE.get(amenity, "bar")
        if is_fast_food(name, tags):
            stats["skipped_fast_food"] += 1
            continue

        if has_nearby(lat, lng):
            stats["skipped_dedupe"] += 1
            continue

        angle = math.degrees(math.atan2(lng - center_lng, lat - center_lat))
        orientation = int(round((angle + 180) % 360))
        orient_label = (
            "Sud" if 135 < orientation <= 225 else
            "Est" if 45 < orientation <= 135 else
            "Nord" if 225 < orientation <= 315 else
            "Ouest"
        )

        doc = {
            "id": str(uuid.uuid4()),
            "name": name.strip()[:200],
            "lat": float(lat),
            "lng": float(lng),
            "orientation_degrees": float(orientation),
            "orientation_label": orient_label,
            "type": ttype,
            "city": city,
            "arrondissement": None,
            "address": tags.get("addr:street") or city,
            "google_rating": 0.0,
            "google_ratings_count": 0,
            "google_place_id": None,
            "google_maps_uri": None,
            "google_photo_name": None,
            "photos": [],
            "photo_url": None,
            "has_cover": False,
            "capacity_estimate": 40,
            "has_terrace_confirmed": False,
            "terrace_source": "osm",
            "osm_id": el.get("id"),
            "osm_amenity": amenity,
            "osm_tags": {k: v for k, v in tags.items() if k in {
                "cuisine", "outdoor_seating", "takeaway", "wheelchair", "phone", "website", "opening_hours"
            }},
            "description_ia": None,
            "ai_description": None,
            "created_at": datetime.now(timezone.utc),
        }
        batch.append(doc)
        existing_pts.append((float(lat), float(lng)))

        if len(batch) >= 200:
            await db.terraces.insert_many(batch)
            stats["inserted"] += len(batch)
            print(f"  [{city} flush] inserted={stats['inserted']}, dedupe_skip={stats['skipped_dedupe']}, ff_skip={stats['skipped_fast_food']}")
            batch = []

    if batch:
        await db.terraces.insert_many(batch)
        stats["inserted"] += len(batch)

    after_total = await db.terraces.count_documents({"city": city})
    dt = time.time() - t0
    print(f"[OSM {city}] DONE in {dt:.0f}s | Stats: {stats} | {before_total} -> {after_total} (+{after_total - before_total})")
    return stats


async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--city", default="Paris", help="City name or 'all' for every city except Paris")
    args = parser.parse_args()

    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ.get("DB_NAME", "soleia")]

    if args.city.lower() == "all":
        cities = [c for c in CITY_BBOXES.keys() if c != "Paris"]
    else:
        if args.city not in CITY_BBOXES:
            print(f"Unknown city '{args.city}'. Available: {list(CITY_BBOXES)}")
            return
        cities = [args.city]

    grand = {"inserted": 0, "skipped_dedupe": 0, "skipped_fast_food": 0, "skipped_no_name": 0, "skipped_no_coords": 0}
    for c in cities:
        s = await seed_city(db, c)
        for k, v in s.items():
            grand[k] += v
        # Small cool-down between cities so Overpass mirrors are happy
        await asyncio.sleep(8)

    print(f"\n[OSM all] GRAND TOTAL: {grand}")
    client.close()


if __name__ == "__main__":
    asyncio.run(main())
