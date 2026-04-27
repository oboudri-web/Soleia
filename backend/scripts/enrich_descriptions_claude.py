#!/usr/bin/env python3
"""
Soleia - Génération de descriptions IA Claude pour les terrasses sans
`description_ia`. Utilise emergentintegrations + EMERGENT_LLM_KEY.

Usage:
    python3 scripts/enrich_descriptions_claude.py [--cities Paris,Lyon] [--limit N] [--dry-run]
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

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
load_dotenv(BACKEND_DIR / ".env")

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ.get("DB_NAME", "soleia")
EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "").strip()

if not EMERGENT_LLM_KEY:
    print("[ERR] EMERGENT_LLM_KEY missing in .env", file=sys.stderr)
    sys.exit(1)

# Imports tardifs (le SDK doit être importé après load_dotenv)
sys.path.insert(0, str(BACKEND_DIR))
from emergentintegrations.llm.chat import LlmChat, UserMessage  # noqa: E402


def orientation_label(degrees: float) -> str:
    """Convertit l'orientation en label cardinal."""
    d = float(degrees or 180) % 360
    if 22.5 <= d < 67.5:   return "Nord-Est"
    if 67.5 <= d < 112.5:  return "Est"
    if 112.5 <= d < 157.5: return "Sud-Est"
    if 157.5 <= d < 202.5: return "Sud"
    if 202.5 <= d < 247.5: return "Sud-Ouest"
    if 247.5 <= d < 292.5: return "Ouest"
    if 292.5 <= d < 337.5: return "Nord-Ouest"
    return "Nord"


CITY_HINTS = {
    "Paris":     "Style Parisien chic, mentionne arrondissement, Seine, quartiers (Marais, Montmartre, Saint-Germain) quand pertinent.",
    "Lyon":      "Style Lyonnais authentique, mentionne Saône, Rhône, Vieux Lyon, Croix-Rousse, Presqu'île quand pertinent.",
    "Marseille": "Style Marseillais ensoleillé, mentionne Vieux-Port, Calanques, soleil méditerranéen quand pertinent.",
    "Nantes":    "Style Nantais, mentionne Loire, île de Nantes, Graslin, Bouffay, quais quand pertinent.",
}


def build_prompt(t: Dict[str, Any]) -> str:
    type_fr = {"bar": "bar", "cafe": "café", "restaurant": "restaurant",
               "rooftop": "rooftop"}.get(t.get("type") or "bar", t.get("type") or "bar")
    ori = orientation_label(t.get("orientation_degrees") or 180)
    rating = t.get("google_rating")
    rating_str = f"Note Google: {rating}/5. " if rating else ""
    addr = t.get("address") or t.get("opendata_address") or ""
    return (
        f"Décris la terrasse du {type_fr} '{t.get('name')}' à {t.get('city')} "
        f"({addr[:60]}). Orientation: {ori}. {rating_str}"
        f"Style: factuel mais sensoriel, premium, 2 phrases, max 30 mots, "
        f"sans guillemets ni préambule."
    )


async def gen_one(t: Dict[str, Any]) -> Optional[str]:
    try:
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"desc-{t.get('id')}",
            system_message=(
                "Tu écris des descriptions courtes et élégantes pour Soleia, "
                "une app premium de recherche de terrasses ensoleillées. "
                "Style premium, inspiré Airbnb, factuel + sensoriel. "
                + CITY_HINTS.get(t.get("city") or "", "")
                + " Réponds UNIQUEMENT avec la description (2 phrases, 30 mots max), "
                "sans guillemets ni préambule."
            ),
        ).with_model("anthropic", "claude-4-sonnet-20250514")
        resp = await chat.send_message(UserMessage(text=build_prompt(t)))
        return (resp or "").strip().strip('"\'').strip()
    except Exception as e:
        print(f"    [ERR] Claude {t.get('name')[:30]}: {e}")
        return None


async def run(cities: List[str], limit: Optional[int], dry_run: bool):
    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]
    coll = db.terraces

    query = {
        "city": {"$in": cities},
        "$or": [
            {"description_ia": None},
            {"description_ia": ""},
            {"description_ia": {"$exists": False}},
        ],
    }
    # Priority: confirmed terraces first, then highest rating
    pipeline = [
        {"$match": query},
        {"$addFields": {
            "_p_conf":   {"$cond": [{"$eq": ["$has_terrace_confirmed", True]}, 0, 1]},
            "_p_rating": {"$multiply": [-1, {"$ifNull": ["$google_rating", 0]}]},
        }},
        {"$sort": {"_p_conf": 1, "_p_rating": 1}},
    ]
    if limit:
        pipeline.append({"$limit": int(limit)})
    pipeline.append({"$project": {
        "id": 1, "name": 1, "city": 1, "type": 1, "address": 1, "opendata_address": 1,
        "orientation_degrees": 1, "has_terrace_confirmed": 1, "google_rating": 1, "_id": 0,
    }})
    docs = await coll.aggregate(pipeline, allowDiskUse=True).to_list(length=None)
    print(f"[CLAUDE] {len(docs)} terrasses à décrire (cities={cities}, limit={limit}, parallel=10)")

    by_city: Dict[str, int] = {c: 0 for c in cities}
    fails = 0
    sem = asyncio.Semaphore(10)  # 10 requêtes Claude concurrentes
    counter = {"i": 0}

    async def worker(t: Dict[str, Any]) -> None:
        nonlocal fails
        async with sem:
            desc = await gen_one(t)
            counter["i"] += 1
            i = counter["i"]
            if not desc:
                fails += 1
                return
            if not dry_run:
                await coll.update_one({"id": t["id"]}, {"$set": {
                    "description_ia": desc,
                    "ai_description": desc,
                    "description_ia_at": time.time(),
                    "description_ia_model": "claude-4-sonnet-20250514",
                }})
            c = t.get("city") or "?"
            by_city[c] = by_city.get(c, 0) + 1
            if i % 50 == 0 or i == 1:
                print(f"  [{i}/{len(docs)}] {c} · {(t.get('name') or '')[:40]} → {desc[:80]}…")

    await asyncio.gather(*(worker(t) for t in docs))

    print("\n=== CLAUDE DESCRIPTIONS DONE ===")
    for c, n in by_city.items():
        print(f"  {c:<11} {n:>5}")
    print(f"  fails: {fails}")

    log = SCRIPT_DIR / "enrich_descriptions_last_run.json"
    log.write_text(json.dumps({"by_city": by_city, "fails": fails,
                               "total_attempted": len(docs)}, indent=2, ensure_ascii=False))
    print(f"\n[LOG] {log}")
    client.close()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--cities", default="Paris,Lyon,Marseille,Nantes")
    p.add_argument("--limit", type=int, default=None,
                   help="Max descriptions to generate this run")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    cities = [c.strip() for c in args.cities.split(",") if c.strip()]
    asyncio.run(run(cities, args.limit, args.dry_run))


if __name__ == "__main__":
    main()
