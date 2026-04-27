#!/usr/bin/env python3
"""
Soleia - Shadow engine GLOBAL : traite TOUTES les terrasses sans shadow_map,
toutes sources confondues (foursquare, osm, opendata, google_places, etc.).

Tri par priorité :
    1. Villes prioritaires (Paris/Lyon/Marseille/Nantes) en premier
    2. Terrasses confirmées en open-data (has_terrace_confirmed=True) avant
    3. Note Google >= 4.0 avant les autres

Usage:
    python3 scripts/shadow_all.py [--limit N] [--cities Paris,Lyon] [--force]
"""
from __future__ import annotations

import asyncio
import os
import sys
import argparse
from datetime import datetime, timezone
import time as _time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(SCRIPT_DIR)
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(BACKEND_DIR, ".env"))

from shadow_engine import compute_shadow_map  # noqa: E402

PRIORITY_CITIES = ["Paris", "Lyon", "Marseille", "Nantes"]


async def run(cities: list[str] | None, limit: int | None, force: bool, sleep_s: float):
    mongo = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = mongo[os.environ.get("DB_NAME", "soleia")]

    query: dict = {}
    if cities:
        query["city"] = {"$in": cities}
    if not force:
        query["has_shadow_analysis"] = {"$ne": True}

    # Priority sort: priority cities first, then has_terrace_confirmed=True,
    # then highest google_rating
    pipeline = [
        {"$match": query},
        {"$addFields": {
            "_prio_city": {
                "$cond": [{"$in": ["$city", PRIORITY_CITIES]}, 0, 1]
            },
            "_prio_conf": {
                "$cond": [{"$eq": ["$has_terrace_confirmed", True]}, 0, 1]
            },
            "_prio_rating": {"$multiply": [-1, {"$ifNull": ["$google_rating", 0]}]},
        }},
        {"$sort": {"_prio_city": 1, "_prio_conf": 1, "_prio_rating": 1}},
    ]
    if limit:
        pipeline.append({"$limit": int(limit)})
    pipeline.append({"$project": {
        "id": 1, "name": 1, "lat": 1, "lng": 1, "city": 1,
        "has_terrace_confirmed": 1, "_id": 0,
    }})

    docs = await db.terraces.aggregate(pipeline, allowDiskUse=True).to_list(length=None)
    print(f"=== Shadow ALL — {len(docs)} docs (cities={cities or 'ALL'} force={force}) ===")
    if not docs:
        print("Nothing to do.")
        return

    ok = fail = 0
    t0 = _time.time()
    for i, t in enumerate(docs, start=1):
        name = (t.get("name") or "?")[:50]
        c = t.get("city") or "?"
        try:
            smap, nb = compute_shadow_map(t["lat"], t["lng"])
            sunny_minutes = sum(1 for v in smap.values() if not v) * 30
            await db.terraces.update_one(
                {"id": t["id"]},
                {"$set": {
                    "shadow_map": smap,
                    "shadow_buildings_count": nb,
                    "shadow_sunny_minutes": sunny_minutes,
                    "shadow_analysis_at": datetime.now(timezone.utc),
                    "shadow_analysis_date": datetime.now(timezone.utc).date().isoformat(),
                    "has_shadow_analysis": True,
                }},
            )
            ok += 1
            if i % 25 == 0 or i == 1:
                rate = i / max(1.0, _time.time() - t0)
                eta = (len(docs) - i) / max(0.001, rate)
                print(f"  [{i}/{len(docs)}] {c} · {name}… OK · {rate:.2f}/s · ETA {eta/60:.0f}min")
        except Exception as e:
            fail += 1
            if fail <= 20 or fail % 50 == 0:
                print(f"  [{i}/{len(docs)}] {c} · {name}… FAIL: {e}")
        _time.sleep(sleep_s)

    print(f"\n=== Done: {ok} ok / {fail} fail / {len(docs)} total ===")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--cities", default="", help="comma-sep, empty = all cities")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--force", action="store_true")
    p.add_argument("--sleep", type=float, default=2.0,
                   help="Sleep seconds between Overpass calls (default 2)")
    args = p.parse_args()
    cities = [c.strip() for c in args.cities.split(",") if c.strip()] or None
    asyncio.run(run(cities, args.limit, args.force, args.sleep))


if __name__ == "__main__":
    main()
