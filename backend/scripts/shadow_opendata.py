#!/usr/bin/env python3
"""
Soleia - Shadow engine pour les terrasses confirmées via open-data.

Cible les docs `opendata_source IN (paris, toulouse, ...)` qui n'ont pas
encore de calcul d'ombre 3D (`has_shadow_analysis != True`). Traite par
ordre de priorité (Paris d'abord car 80 % des matches), 4s entre chaque
appel pour respecter Overpass.

Usage:
    python3 scripts/shadow_opendata.py [--cities Paris,Toulouse] [--limit N] [--force]
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


async def run(cities: list[str] | None, limit: int | None, force: bool):
    mongo = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = mongo[os.environ.get("DB_NAME", "soleia")]

    query: dict = {"opendata_source": {"$exists": True}}
    if cities:
        query["opendata_source"] = {"$in": [c.lower() for c in cities]}
    if not force:
        query["has_shadow_analysis"] = {"$ne": True}

    cur = db.terraces.find(query).sort("opendata_source", 1)  # paris first alphabetically
    docs = await cur.to_list(length=None)
    if limit:
        docs = docs[:limit]

    print(f"=== Shadow OPENDATA — {len(docs)} docs (cities={cities or 'ALL'} force={force}) ===")
    ok = fail = 0
    for i, t in enumerate(docs, start=1):
        name = t.get("name", "?")
        c = t.get("city", "?")
        src = t.get("opendata_source", "?")
        print(f"  [{i}/{len(docs)}] {c} · {src} · {name[:50]}…", end=" ", flush=True)
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
            print(f"OK ({nb} bât., {sunny_minutes/60:.1f}h soleil)")
            ok += 1
        except Exception as e:
            print(f"FAIL: {e}")
            fail += 1
        _time.sleep(4)

    print(f"\n=== Done: {ok} ok / {fail} fail / {len(docs)} total ===")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--cities", default="", help="paris,toulouse — empty = all opendata sources")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--force", action="store_true")
    args = p.parse_args()
    cities = [c.strip() for c in args.cities.split(",") if c.strip()] or None
    asyncio.run(run(cities, args.limit, args.force))


if __name__ == "__main__":
    main()
