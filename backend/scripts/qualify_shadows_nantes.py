"""
Batch script: compute shadow map for all confirmed Nantes terraces.
Usage: python3 scripts/qualify_shadows_nantes.py [--limit N] [--city Nantes]
"""
from __future__ import annotations

import asyncio
import os
import sys
import argparse
from datetime import datetime, timezone

# Ensure parent dir importable
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(SCRIPT_DIR)
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(BACKEND_DIR, ".env"))

from shadow_engine import compute_shadow_map  # noqa: E402


async def run(city: str, limit: int | None, force: bool, include_osm: bool = False, osm_only: bool = False):
    mongo_url = os.environ["MONGO_URL"]
    db_name = os.environ.get("DB_NAME", "soleia")
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    if osm_only:
        # Only OSM-sourced docs lacking shadow analysis
        query = {
            "city": city,
            "terrace_source": "osm",
        }
    elif include_osm:
        # Confirmed terraces + OSM new docs (no has_terrace_confirmed constraint on OSM)
        query = {
            "city": city,
            "$or": [
                {"has_terrace_confirmed": True},
                {"has_terrace_confirmed": {"$exists": False}},
                {"terrace_source": "osm"},
            ],
        }
    else:
        query = {
            "city": city,
            "$or": [
                {"has_terrace_confirmed": True},
                {"has_terrace_confirmed": {"$exists": False}},
            ],
        }
    if not force:
        query["has_shadow_analysis"] = {"$ne": True}

    cursor = db.terraces.find(query)
    # No hard cap : Paris OSM ≈ 3545 docs
    terraces = await cursor.to_list(length=None)
    if limit:
        terraces = terraces[:limit]

    total = len(terraces)
    print(f"=== Shadow qualification for {city} (osm_only={osm_only}, include_osm={include_osm}) ===")
    print(f"Processing {total} terraces (force={force})")

    ok, fail = 0, 0
    import time as _time
    for i, t in enumerate(terraces, start=1):
        name = t.get("name", "?")
        print(f"  [{i}/{total}] {name}...", end=" ", flush=True)
        try:
            smap, nb = compute_shadow_map(t["lat"], t["lng"])
            sunny_minutes = sum(1 for v in smap.values() if not v) * 30
            await db.terraces.update_one(
                {"id": t["id"]},
                {
                    "$set": {
                        "shadow_map": smap,
                        "shadow_buildings_count": nb,
                        "shadow_sunny_minutes": sunny_minutes,
                        "shadow_analysis_at": datetime.now(timezone.utc),
                        "shadow_analysis_date": datetime.now(timezone.utc)
                        .date()
                        .isoformat(),
                        "has_shadow_analysis": True,
                    }
                },
            )
            print(f"OK ({nb} batiments, {sunny_minutes / 60:.1f}h soleil)")
            ok += 1
        except Exception as e:
            print(f"FAIL: {e}")
            fail += 1
        # Gentle pacing to avoid Overpass rate-limiting
        _time.sleep(4)

    print()
    print(f"=== Done: {ok} succeeded, {fail} failed, {total} total ===")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--city", default="Nantes")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-process even if has_shadow_analysis=True",
    )
    parser.add_argument("--include-osm", action="store_true", help="Also process terrace_source=osm docs (has_terrace_confirmed may be False)")
    parser.add_argument("--osm-only", action="store_true", help="Only process terrace_source=osm docs")
    args = parser.parse_args()
    asyncio.run(run(args.city, args.limit, args.force, include_osm=args.include_osm, osm_only=args.osm_only))


if __name__ == "__main__":
    main()
