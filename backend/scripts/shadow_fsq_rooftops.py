#!/usr/bin/env python3
"""
Soleia - Shadow engine pour les rooftops Foursquare.

Lance le calcul d'ombre 3D (Overpass + shadow_engine.py) sur les
établissements terrace_source=foursquare ET (type=rooftop OU --all-types).

Usage:
    python3 scripts/shadow_fsq_rooftops.py [--city Paris] [--all-types] [--limit N]

Pacing : 4s entre chaque terrasse pour respecter Overpass.
~199 rooftops × 4s ≈ 13 min ; ~1276 docs FSQ × 4s ≈ 85 min.
"""
from __future__ import annotations

import asyncio
import os
import sys
import argparse
from datetime import datetime, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(SCRIPT_DIR)
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(BACKEND_DIR, ".env"))

from shadow_engine import compute_shadow_map  # noqa: E402


async def run(city: str | None, all_types: bool, limit: int | None, force: bool):
    mongo = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = mongo[os.environ.get("DB_NAME", "soleia")]

    query: dict = {"terrace_source": "foursquare"}
    if not all_types:
        query["type"] = "rooftop"
    if city:
        query["city"] = city
    if not force:
        query["has_shadow_analysis"] = {"$ne": True}

    cur = db.terraces.find(query)
    docs = await cur.to_list(length=None)
    if limit:
        docs = docs[:limit]

    print(f"=== Shadow FSQ — {len(docs)} docs (city={city or 'ALL'} all_types={all_types} force={force}) ===")
    import time as _time
    ok = fail = 0
    for i, t in enumerate(docs, start=1):
        name = t.get("name", "?")
        c = t.get("city", "?")
        ttype = t.get("type", "?")
        print(f"  [{i}/{len(docs)}] {c} · {ttype} · {name}…", end=" ", flush=True)
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
            print(f"OK ({nb} bâtiments, {sunny_minutes/60:.1f}h soleil)")
            ok += 1
        except Exception as e:
            print(f"FAIL: {e}")
            fail += 1
        _time.sleep(4)

    print(f"\n=== Done: {ok} ok / {fail} fail / {len(docs)} total ===")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--city", default=None, help="Restrict to a single city (else all)")
    p.add_argument("--all-types", action="store_true", help="Process all FSQ types (rooftop+bar+cafe), not just rooftop")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--force", action="store_true", help="Re-process even if has_shadow_analysis=True")
    args = p.parse_args()
    asyncio.run(run(args.city, args.all_types, args.limit, args.force))


if __name__ == "__main__":
    main()
