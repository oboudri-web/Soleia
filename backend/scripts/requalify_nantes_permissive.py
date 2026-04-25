"""
Soleia - Re-qualification PERMISSIVE pour Nantes.
Nantes avait 21/751 = 2.8% confirmed (anomalie, seuil trop strict).
Ce script :
  1. Cible Nantes avec has_terrace_confirmed=False ET terrace_source=street_view_ai
  2. Re-analyse avec un prompt PLUS PERMISSIF (tables/chaises OU parasol OU
     awning OU seating area visible OU trottoir large devant l'établissement)
  3. Ne touche PAS aux terrasses déjà confirmées (True)

Usage:
    cd /app/backend && python3 scripts/requalify_nantes_permissive.py [--limit N]
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from anthropic import AsyncAnthropic  # noqa: E402

from scripts.qualify_terraces import get_street_view_panorama, _parse_claude_json  # noqa: E402

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
GOOGLE_API_KEY = os.environ.get("GOOGLE_PLACES_API_KEY")
_anthropic_client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None


PERMISSIVE_PROMPT = (
    'Photo Street View de l\'établissement "{name}" (type: {ttype}).\n\n'
    "Réponds UNIQUEMENT en JSON strict :\n"
    "{{\n"
    '  "has_terrace": true|false,\n'
    '  "confidence": "high"|"medium"|"low",\n'
    '  "covered": true|false|null,\n'
    '  "capacity_estimate": "small"|"medium"|"large"|null,\n'
    '  "notes": "une phrase max"\n'
    "}}\n\n"
    "Mode PERMISSIF (on veut maximiser le rappel sur Nantes).\n"
    "has_terrace = true si la photo montre OU SUGGÈRE la présence d'une terrasse extérieure :\n"
    "- tables/chaises en extérieur (OUI bien sûr)\n"
    "- parasols / auvents / pergolas / store-banne devant l'établissement\n"
    "- trottoir large aménagé juste devant l'enseigne\n"
    "- une zone délimitée (bac à fleurs, paravent, barrière) devant le commerce\n"
    "- vitrine avec tables visibles à l'intérieur mais trottoir utilisable\n"
    "- coin de rue piétonne ou square devant le bar/café/restaurant\n"
    "has_terrace = false SEULEMENT si :\n"
    "- l'image ne montre clairement PAS l'établissement\n"
    "- l'établissement est au 1er étage / dans un centre commercial fermé\n"
    "- pas d'espace extérieur possible (mur directement contre chaussée)\n"
    "En cas de doute raisonnable => has_terrace=true avec confidence=low."
)


async def analyze_permissive(image_b64: str, name: str, ttype: str) -> dict:
    try:
        content = [
            {
                "type": "image",
                "source": {"type": "base64", "media_type": "image/jpeg", "data": image_b64},
            },
            {"type": "text", "text": PERMISSIVE_PROMPT.format(name=name, ttype=ttype)},
        ]
        resp = await _anthropic_client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=220,
            system=(
                "Tu es un expert en analyse d'images urbaines avec un biais PERMISSIF "
                "pour la détection de terrasses extérieures. Réponds UNIQUEMENT en JSON strict."
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
        return {"has_terrace": None, "confidence": "low", "notes": f"error: {str(e)[:100]}"}


async def run(limit: int | None):
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ.get("DB_NAME", "suntterrace_db")]

    # Nantes terrasses non-qualifiées (google_places) OU rejetées par l'ancien passage
    query = {
        "city": "Nantes",
        "has_terrace_confirmed": False,
        "terrace_source": {"$in": ["street_view_ai", "google_places", "street_view_no_image"]},
    }
    cursor = db.terraces.find(query)
    terraces = await cursor.to_list(length=None)
    if limit:
        terraces = terraces[:limit]

    total = len(terraces)
    print(f"=== Re-qualification PERMISSIVE Nantes ===")
    print(f"{total} terrasses à re-analyser")
    print()

    upgraded = 0
    kept_false = 0
    cost = 0.0
    async with httpx.AsyncClient(timeout=30) as http:
        for i, t in enumerate(terraces, 1):
            name = t["name"]
            ttype = t.get("type", "bar")
            images = await get_street_view_panorama(t["lat"], t["lng"], http)
            cost += 0.007
            if not images:
                kept_false += 1
                continue
            analysis = await analyze_permissive(images[0], name, ttype)
            cost += 0.005
            if analysis.get("has_terrace") is True:
                await db.terraces.update_one(
                    {"id": t["id"]},
                    {
                        "$set": {
                            "has_terrace_confirmed": True,
                            "terrace_source": "street_view_ai_permissive",
                            "terrace_confidence": analysis.get("confidence"),
                            "terrace_covered": analysis.get("covered"),
                            "terrace_capacity": analysis.get("capacity_estimate"),
                            "terrace_ai_notes": analysis.get("notes"),
                        }
                    },
                )
                upgraded += 1
            else:
                kept_false += 1

            if i % 20 == 0:
                print(f"  {i}/{total} - upgraded={upgraded}, kept_false={kept_false}, cost~${cost:.2f}")
            await asyncio.sleep(0.1)

    print()
    print(f"=== TERMINE: {upgraded} terrasses UPGRADED to confirmed, "
          f"{kept_false} kept false. Cout ~${cost:.2f} ===")
    client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    asyncio.run(run(args.limit))
