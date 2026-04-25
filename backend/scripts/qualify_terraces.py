"""
Soleia - Qualification automatique des terrasses via Street View + Claude Vision.

Utilise :
  - Google Street View Static API (avec metadata check)
  - Claude Sonnet 4 Vision via EMERGENT_LLM_KEY (emergentintegrations)

Périmètre : toutes les villes sauf Paris, hors terrasses Nantes manuelles.
Ne traite pas celles déjà qualifiées (terrace_source in street_view_ai / manual / street_view_no_image).

Run:
    cd /app/backend && python scripts/qualify_terraces.py
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from emergentintegrations.llm.chat import LlmChat, UserMessage, ImageContent  # noqa: E402
from anthropic import AsyncAnthropic  # noqa: E402

EMERGENT_KEY = os.environ.get("EMERGENT_LLM_KEY")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
_anthropic_client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None

GOOGLE_API_KEY = os.environ.get("GOOGLE_PLACES_API_KEY")
EMERGENT_KEY = os.environ.get("EMERGENT_LLM_KEY")

STREET_VIEW_URL = "https://maps.googleapis.com/maps/api/streetview"
STREET_VIEW_METADATA = "https://maps.googleapis.com/maps/api/streetview/metadata"

CITIES_TO_QUALIFY = [
    "Toulouse", "Nice", "Montpellier",
]


import math


def _bearing(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Calcule le cap (0-360°) pour regarder depuis (lat1,lng1) vers (lat2,lng2)."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlng = math.radians(lng2 - lng1)
    y = math.sin(dlng) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlng)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


async def get_street_view_panorama(lat: float, lng: float, client: httpx.AsyncClient) -> list[str]:
    """
    Retourne 1 seule image Street View (heading calculé vers l'établissement)
    pour minimiser les coûts — ~$0.007 par place au lieu de $0.021 à 3 images.
    """
    try:
        meta = await client.get(
            STREET_VIEW_METADATA,
            params={"location": f"{lat},{lng}", "key": GOOGLE_API_KEY},
            timeout=10,
        )
        if meta.status_code != 200:
            return []
        meta_data = meta.json() or {}
        if meta_data.get("status") != "OK":
            return []

        pano_id = meta_data.get("pano_id")
        pano_loc = meta_data.get("location") or {}
        pano_lat = pano_loc.get("lat")
        pano_lng = pano_loc.get("lng")

        base_heading = 0.0
        if pano_lat is not None and pano_lng is not None:
            dx = (pano_lat - lat) * 111000
            dy = (pano_lng - lng) * 85000
            if (dx * dx + dy * dy) ** 0.5 > 3:
                base_heading = _bearing(pano_lat, pano_lng, lat, lng)

        params = {
            "size": "480x320",
            "fov": 90,
            "heading": int(base_heading),
            "pitch": 5,
            "key": GOOGLE_API_KEY,
        }
        if pano_id:
            params["pano"] = pano_id
        else:
            params["location"] = f"{lat},{lng}"
        resp = await client.get(STREET_VIEW_URL, params=params, timeout=15)
        if resp.status_code == 200 and len(resp.content) > 5000:
            return [base64.b64encode(resp.content).decode("utf-8")]
        return []
    except Exception as e:
        print(f"    Street View error: {e}")
        return []


def _parse_claude_json(text: str) -> dict:
    clean = text.strip().replace("```json", "").replace("```", "").strip()
    # Tente de récupérer le premier objet JSON même si texte autour
    start = clean.find("{")
    end = clean.rfind("}")
    if start >= 0 and end > start:
        clean = clean[start : end + 1]
    try:
        return json.loads(clean)
    except Exception:
        return {}


async def analyze_with_claude(images_b64: list[str], name: str, terrace_type: str) -> dict:
    """
    Analyse 1 image Street View via Claude Sonnet 4 Vision (API Anthropic directe).
    """
    try:
        if not images_b64:
            return {"has_terrace": None, "confidence": "low", "notes": "no_image"}
        if _anthropic_client is None:
            return {"has_terrace": None, "confidence": "low", "notes": "no_api_key"}

        prompt = (
            f'Photo Street View de l\'établissement "{name}" (type: {terrace_type}).\n\n'
            "Réponds UNIQUEMENT en JSON strict :\n"
            "{\n"
            '  "has_terrace": true|false,\n'
            '  "confidence": "high"|"medium"|"low",\n'
            '  "covered": true|false|null,\n'
            '  "capacity_estimate": "small"|"medium"|"large"|null,\n'
            '  "notes": "une phrase max"\n'
            "}\n\n"
            "has_terrace = true si la photo montre des tables/chaises en extérieur "
            "devant un bar/café/restaurant (trottoir, cour, rooftop).\n"
            "Si l'image ne montre pas l'établissement ou trop éloigné => has_terrace=false."
        )

        content = [{
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": images_b64[0]},
        }, {"type": "text", "text": prompt}]

        resp = await _anthropic_client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=220,
            system=(
                "Tu es un expert en analyse d'images urbaines. "
                "Tu analyses une photo Street View pour détecter une terrasse extérieure. "
                "Réponds UNIQUEMENT en JSON strict, sans markdown."
            ),
            messages=[{"role": "user", "content": content}],
        )
        text = resp.content[0].text if resp.content else ""
        parsed = _parse_claude_json(text)
        if not parsed:
            return {"has_terrace": None, "confidence": "low", "notes": "parse_error"}
        return {
            "has_terrace": bool(parsed.get("has_terrace")) if parsed.get("has_terrace") is not None else None,
            "confidence": parsed.get("confidence") or "low",
            "covered": parsed.get("covered"),
            "capacity_estimate": parsed.get("capacity_estimate"),
            "notes": (parsed.get("notes") or "")[:200],
        }
    except Exception as e:
        print(f"    Claude Vision error: {str(e)[:120]}")
        return {"has_terrace": None, "confidence": "low", "notes": f"error: {str(e)[:100]}"}


async def qualify_city(city_name: str, db) -> tuple[int, int, float]:
    print(f"\nQualification {city_name}...")

    query = {
        "city": city_name,
        "terrace_source": {"$nin": ["street_view_ai", "manual", "street_view_no_image"]},
    }
    cursor = db.terraces.find(query)
    terraces = await cursor.to_list(length=None)
    print(f"  {len(terraces)} etablissements a qualifier")

    qualified = 0
    has_terrace = 0
    cost_estimate = 0.0

    async with httpx.AsyncClient(timeout=30) as client:
        for i, terrace in enumerate(terraces, 1):
            lat = terrace["lat"]
            lng = terrace["lng"]
            name = terrace["name"]
            ttype = terrace.get("type", "bar")

            images = await get_street_view_panorama(lat, lng, client)
            cost_estimate += 0.007  # 1 image SV = $0.007

            if not images:
                await db.terraces.update_one(
                    {"id": terrace["id"]},
                    {"$set": {
                        "has_terrace_confirmed": False,
                        "terrace_source": "street_view_no_image",
                    }},
                )
                continue

            analysis = await analyze_with_claude(images, name, ttype)
            cost_estimate += 0.005

            has_terrace_result = analysis.get("has_terrace")
            update = {
                "has_terrace_confirmed": has_terrace_result is True,
                "terrace_source": "street_view_ai",
                "terrace_confidence": analysis.get("confidence"),
                "terrace_covered": analysis.get("covered"),
                "terrace_capacity": analysis.get("capacity_estimate"),
                "terrace_ai_notes": analysis.get("notes"),
            }
            await db.terraces.update_one({"id": terrace["id"]}, {"$set": update})

            qualified += 1
            if has_terrace_result:
                has_terrace += 1

            await asyncio.sleep(0.1)

            if qualified % 20 == 0:
                print(
                    f"  {qualified}/{len(terraces)} - {has_terrace} terrasses detectees "
                    f"- ~${cost_estimate:.2f}"
                )

    print(
        f"\n  {city_name}: {has_terrace} terrasses confirmees, "
        f"{qualified - has_terrace} masquees, ~${cost_estimate:.2f}"
    )
    return qualified, has_terrace, cost_estimate


async def main():
    if not GOOGLE_API_KEY:
        print("GOOGLE_PLACES_API_KEY absent. Abort.")
        return
    if not EMERGENT_KEY:
        print("EMERGENT_LLM_KEY absent. Abort.")
        return

    # CLI override: --city X  (space-separated list). Falls back to CITIES_TO_QUALIFY.
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--city",
        nargs="+",
        default=None,
        help="Override list of cities (e.g. --city Paris). Default: CITIES_TO_QUALIFY module var.",
    )
    args = parser.parse_args()
    cities_to_process = args.city or CITIES_TO_QUALIFY
    print(f"Cities to qualify: {cities_to_process}")

    mongo_url = os.environ["MONGO_URL"]
    db_name = os.environ.get("DB_NAME", "suntterrace_db")
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    total_qualified = 0
    total_ok = 0
    total_cost = 0.0

    for city in cities_to_process:
        q, h, c = await qualify_city(city, db)
        total_qualified += q
        total_ok += h
        total_cost += c
        print(f"  Cout cumul: ~${total_cost:.2f}")
        await asyncio.sleep(1.5)

    print("\n=== TERMINE ===")
    print(f"Qualifies: {total_qualified}")
    print(f"Terrasses confirmees: {total_ok}")
    print(f"Masquees (sans terrasse): {total_qualified - total_ok}")
    print(f"Cout total: ~${total_cost:.2f} / 300$")
    client.close()


if __name__ == "__main__":
    asyncio.run(main())
