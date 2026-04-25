"""
Soleia - Enrichissement via Google Places Details API (New).

Pour chaque terrasse confirmée (hors Paris, enrichie séparément via le pipeline Paris),
fetch les détails manquants (horaires, téléphone, site web, prix, lien Google Maps).

Idempotent : skip les terrasses déjà enrichies (flag `details_enriched_at`).

Usage :
    cd /app/backend && python scripts/enrich_details.py
    cd /app/backend && python scripts/enrich_details.py --city Lyon --force

ENV requis :
    MONGO_URL, DB_NAME, GOOGLE_PLACES_API_KEY
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

GOOGLE_API_KEY = os.environ["GOOGLE_PLACES_API_KEY"]

PLACE_DETAILS_URL = "https://places.googleapis.com/v1/places/{place_id}"

FIELD_MASK = ",".join(
    [
        "id",
        "displayName",
        "regularOpeningHours",
        "currentOpeningHours",
        "internationalPhoneNumber",
        "nationalPhoneNumber",
        "websiteUri",
        "priceLevel",
        "googleMapsUri",
        "reservable",
        "servesVegetarianFood",
        "servesCoffee",
    ]
)

PRICE_LEVEL_MAP = {
    "PRICE_LEVEL_FREE": 0,
    "PRICE_LEVEL_INEXPENSIVE": 1,
    "PRICE_LEVEL_MODERATE": 2,
    "PRICE_LEVEL_EXPENSIVE": 3,
    "PRICE_LEVEL_VERY_EXPENSIVE": 4,
}

DEFAULT_CITIES = ["Lyon", "Marseille", "Bordeaux", "Nantes", "Toulouse", "Nice", "Montpellier"]


async def fetch_details(place_id: str, client: httpx.AsyncClient) -> Optional[dict]:
    """Fetch place details (New Places API). Returns a dict or None on failure."""
    url = PLACE_DETAILS_URL.format(place_id=place_id)
    try:
        resp = await client.get(
            url,
            headers={
                "X-Goog-Api-Key": GOOGLE_API_KEY,
                "X-Goog-FieldMask": FIELD_MASK,
            },
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"    error for {place_id}: {e}")
        return None


def normalise(raw: dict) -> dict:
    """Map API fields into our DB schema."""
    out: dict = {}

    opening_raw = raw.get("regularOpeningHours") or raw.get("currentOpeningHours")
    if opening_raw:
        out["opening_hours"] = {
            "weekday_descriptions": opening_raw.get("weekdayDescriptions") or [],
            "periods": opening_raw.get("periods") or [],
        }

    phone = raw.get("internationalPhoneNumber") or raw.get("nationalPhoneNumber")
    if phone:
        out["phone_number"] = phone

    website = raw.get("websiteUri")
    if website:
        out["website_uri"] = website

    price = raw.get("priceLevel")
    if price and price in PRICE_LEVEL_MAP:
        out["price_level"] = PRICE_LEVEL_MAP[price]

    maps_uri = raw.get("googleMapsUri")
    if maps_uri:
        out["google_maps_uri"] = maps_uri

    if raw.get("reservable") is not None:
        out["reservable"] = bool(raw["reservable"])

    return out


async def enrich_city(city: str, db, force: bool, only_confirmed: bool = False, max_docs: int | None = None) -> tuple[int, int]:
    print(f"\n=== Enrich {city} ===")
    query = {
        "city": city,
        "google_place_id": {"$nin": [None, ""]},
        # Exclure les fast-food (cohérent avec la policy affichage)
        "type": {"$ne": "fast_food"},
    }
    if only_confirmed:
        query["has_terrace_confirmed"] = True
    if not force:
        query["details_enriched_at"] = {"$exists": False}

    cursor = db.terraces.find(query, {"id": 1, "google_place_id": 1, "name": 1, "_id": 0})
    cap = max_docs if max_docs and max_docs > 0 else 10000
    todo = await cursor.to_list(cap)
    total = len(todo)
    print(f"  {total} terrasses à enrichir (cap={cap})")

    ok, fail = 0, 0
    async with httpx.AsyncClient(timeout=15) as client:
        for i, t in enumerate(todo, 1):
            pid = t["google_place_id"]
            name = t.get("name", "?")
            print(f"  [{i}/{total}] {name}...", end=" ", flush=True)
            raw = await fetch_details(pid, client)
            if raw is None:
                print("skip (no data)")
                fail += 1
                await db.terraces.update_one(
                    {"id": t["id"]},
                    {"$set": {"details_enriched_at": datetime.now(timezone.utc), "details_fetch_failed": True}},
                )
                continue
            patch = normalise(raw)
            patch["details_enriched_at"] = datetime.now(timezone.utc)
            patch["details_fetch_failed"] = False
            await db.terraces.update_one({"id": t["id"]}, {"$set": patch})
            ok += 1
            tags = []
            if "opening_hours" in patch:
                tags.append("hrs")
            if "phone_number" in patch:
                tags.append("tel")
            if "website_uri" in patch:
                tags.append("web")
            if "price_level" in patch:
                tags.append(f"€{patch['price_level']}")
            print("OK " + " ".join(tags) if tags else "OK")
            await asyncio.sleep(0.15)  # gentle pacing

    print(f"  Done: {ok} enrichies / {fail} sans data")
    return ok, fail


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--city", nargs="+", default=None, help="Cities to enrich (default: all except Paris)")
    parser.add_argument("--force", action="store_true", help="Re-enrich even if already enriched")
    parser.add_argument("--max", dest="max_docs", type=int, default=None, help="Cap the number of docs to enrich in this run (budget safety)")
    args = parser.parse_args()

    cities = args.city or DEFAULT_CITIES
    print(f"Cities to enrich: {cities} | max={args.max_docs or 'unlimited'}")

    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ.get("DB_NAME", "soleia")]

    total_ok, total_fail = 0, 0
    remaining_budget = args.max_docs
    for c in cities:
        if remaining_budget is not None and remaining_budget <= 0:
            print(f"\n[SKIP {c}] budget --max reached")
            continue
        ok, fail = await enrich_city(c, db, args.force, max_docs=remaining_budget)
        total_ok += ok
        total_fail += fail
        if remaining_budget is not None:
            remaining_budget -= (ok + fail)

    print(f"\n=== TERMINE: {total_ok} enrichies / {total_fail} sans data / cost ~${(total_ok + total_fail) * 0.017:.2f} ===")
    client.close()


if __name__ == "__main__":
    asyncio.run(main())
