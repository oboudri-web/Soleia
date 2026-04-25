"""
Soleia - Enrich existing Nantes terraces with Google Places API (New).

Version permissive : les coords manuelles Nantes peuvent être imprécises
(jusqu'à ~1 km d'écart). On accepte jusqu'à 1500 m et on met à jour les
vraies coordonnées Google pour améliorer la précision solaire.

Run:
    cd /app/backend && python scripts/enrich_nantes.py

ENV requis:
    MONGO_URL, DB_NAME, GOOGLE_PLACES_API_KEY
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Optional

import httpx
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from scripts.seed_cities import GOOGLE_TEXTSEARCH_URL, _resolve_photo_uri  # noqa: E402

API_KEY = os.environ.get("GOOGLE_PLACES_API_KEY", "").strip() or None


async def enrich_permissive(name: str, lat: float, lng: float, client: httpx.AsyncClient) -> dict:
    """Variante sans filtre de distance - on trust le locationBias large."""
    if not API_KEY:
        return {}
    try:
        resp = await client.post(
            GOOGLE_TEXTSEARCH_URL,
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": API_KEY,
                "X-Goog-FieldMask": ",".join(
                    [
                        "places.id",
                        "places.displayName",
                        "places.rating",
                        "places.userRatingCount",
                        "places.photos",
                        "places.formattedAddress",
                        "places.location",
                        "places.googleMapsUri",
                    ]
                ),
            },
            json={
                "textQuery": f"{name} Nantes",
                "maxResultCount": 1,
                "locationBias": {
                    "circle": {
                        "center": {"latitude": lat, "longitude": lng},
                        "radius": 2000.0,
                    }
                },
            },
            timeout=15,
        )
        if resp.status_code >= 400:
            return {}
        places = (resp.json() or {}).get("places") or []
        if not places:
            return {}

        place = places[0]
        loc = place.get("location") or {}
        photos = place.get("photos") or []
        photo_url: Optional[str] = None
        if photos:
            photo_url = await _resolve_photo_uri(photos[0].get("name"), client)

        return {
            "google_place_id": place.get("id"),
            "google_rating": place.get("rating"),
            "google_ratings_count": place.get("userRatingCount", 0),
            "google_maps_uri": place.get("googleMapsUri"),
            "google_address": place.get("formattedAddress"),
            "photos": [photo_url] if photo_url else [],
            "google_lat": loc.get("latitude"),
            "google_lng": loc.get("longitude"),
            "display_name": place.get("displayName", {}).get("text"),
        }
    except Exception as e:
        print(f"    Error {name}: {e}")
        return {}


async def main():
    if not API_KEY:
        print("GOOGLE_PLACES_API_KEY absent - rien a faire.")
        return

    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ.get("DB_NAME", "suntterrace_db")]

    cursor = db.terraces.find({"city": "Nantes"}, {"_id": 0})
    terraces = await cursor.to_list(1000)
    print(f"{len(terraces)} terrasses Nantes a enrichir...")

    enriched = 0
    async with httpx.AsyncClient(timeout=30) as http:
        for t in terraces:
            data = await enrich_permissive(t["name"], t["lat"], t["lng"], http)
            await asyncio.sleep(0.05)
            if not data:
                print(f"  SKIP {t['name']}")
                continue

            update = {
                "google_place_id": data.get("google_place_id"),
                "google_maps_uri": data.get("google_maps_uri"),
                "google_ratings_count": data.get("google_ratings_count", 0),
            }
            if data.get("google_rating"):
                update["google_rating"] = data["google_rating"]
            if data.get("photos"):
                update["photos"] = data["photos"]
                update["photo_url"] = data["photos"][0]
            if data.get("google_address"):
                update["address"] = data["google_address"]
            # Remplace par les coords Google (plus précises) si l'écart reste raisonnable
            if data.get("google_lat") and data.get("google_lng"):
                dx = (data["google_lat"] - t["lat"]) * 111000
                dy = (data["google_lng"] - t["lng"]) * 85000
                dist = (dx * dx + dy * dy) ** 0.5
                if dist < 1500:
                    update["lat"] = data["google_lat"]
                    update["lng"] = data["google_lng"]

            await db.terraces.update_one({"id": t["id"]}, {"$set": update})
            enriched += 1
            print(
                f"  OK {t['name']} -> {data.get('google_rating')} "
                f"({data.get('google_ratings_count')} avis) "
                f"[{data.get('display_name')}]"
            )

    print(f"\nEnrichies: {enriched}/{len(terraces)}")
    client.close()


if __name__ == "__main__":
    asyncio.run(main())
