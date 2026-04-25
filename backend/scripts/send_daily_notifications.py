"""
Soleia - Daily morning push notifications (à lancer via cron à 08h30).

Pour chaque ville active :
 1. Vérifie la météo (via notre endpoint /api/weather/{city}).
 2. Skip si `cloud_cover > 70` (ciel très couvert).
 3. Compte les terrasses ensoleillées maintenant.
 4. Envoie un message Expo Push à tous les tokens enregistrés pour la ville.

Usage :
    python3 scripts/send_daily_notifications.py             # toutes les villes
    python3 scripts/send_daily_notifications.py --city Lyon # une ville
    python3 scripts/send_daily_notifications.py --dry-run   # pas d'envoi réel
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from sun_engine import compute_sun_status_dynamic  # noqa: E402
from shadow_engine import lookup_shadow_blocked  # noqa: E402

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
DEFAULT_CITIES = ["Paris", "Lyon", "Marseille", "Bordeaux", "Nantes", "Toulouse", "Nice", "Montpellier"]
CLOUD_COVER_THRESHOLD = 70


async def get_weather(city: str, client: httpx.AsyncClient) -> dict | None:
    try:
        resp = await client.get(f"http://localhost:8001/api/weather/{city}", timeout=10)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


async def count_sunny_terraces(city: str, db, now: datetime) -> int:
    """Count how many confirmed terraces in this city are in the sun RIGHT NOW."""
    cursor = db.terraces.find(
        {"city": city, "has_terrace_confirmed": True},
        {"_id": 0, "lat": 1, "lng": 1, "orientation_degrees": 1, "shadow_map": 1},
    )
    terraces = await cursor.to_list(5000)
    count = 0
    for t in terraces:
        info = compute_sun_status_dynamic(t["lat"], t["lng"], t["orientation_degrees"], now)
        if not info.get("is_sunny"):
            continue
        # Honor shadow_map if present
        smap = t.get("shadow_map")
        if smap:
            try:
                from zoneinfo import ZoneInfo
                blocked = lookup_shadow_blocked(smap, now.astimezone(ZoneInfo("Europe/Paris")))
                if blocked:
                    continue
            except Exception:
                pass
        count += 1
    return count


async def send_batch_expo(messages: list[dict], client: httpx.AsyncClient) -> tuple[int, int]:
    """Send messages to Expo Push API (chunks of 100). Returns (ok_count, fail_count)."""
    ok, fail = 0, 0
    for i in range(0, len(messages), 100):
        batch = messages[i : i + 100]
        try:
            resp = await client.post(
                EXPO_PUSH_URL,
                json=batch,
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                timeout=20,
            )
            if resp.status_code == 200:
                data = resp.json()
                tickets = data.get("data", [])
                for t in tickets:
                    if t.get("status") == "ok":
                        ok += 1
                    else:
                        fail += 1
            else:
                fail += len(batch)
                print(f"    Expo API error {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            fail += len(batch)
            print(f"    Expo API exception: {e}")
    return ok, fail


async def process_city(city: str, db, client: httpx.AsyncClient, dry_run: bool) -> None:
    print(f"\n=== {city} ===")
    weather = await get_weather(city, client)
    if not weather:
        print("  ⚠️ météo indisponible, skip")
        return
    cloud_cover = weather.get("cloud_cover", 100)
    if cloud_cover > CLOUD_COVER_THRESHOLD:
        print(f"  ⛅ trop couvert ({cloud_cover}%), skip")
        return

    now = datetime.now(timezone.utc)
    sunny = await count_sunny_terraces(city, db, now)
    if sunny == 0:
        print("  🌑 aucune terrasse ensoleillée, skip")
        return

    tokens_cursor = db.push_tokens.find({"city": city, "enabled": {"$ne": False}})
    tokens = await tokens_cursor.to_list(20000)
    if not tokens:
        print("  📭 aucun token enregistré, skip")
        return

    body = f"Beau temps à {city} — {sunny} terrasse{'s' if sunny > 1 else ''} au soleil près de toi ☀️"
    messages = [
        {
            "to": t["token"],
            "title": "Soleia ☀️",
            "body": body,
            "sound": "default",
            "data": {"city": city, "action": "open_map"},
        }
        for t in tokens
    ]
    print(f"  📨 {len(messages)} notifications à envoyer")
    if dry_run:
        print(f"  (dry-run) preview: {messages[0]}")
        return
    ok, fail = await send_batch_expo(messages, client)
    print(f"  ✅ {ok} OK, ❌ {fail} failed")


async def main(cities: list[str], dry_run: bool):
    client_mongo = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client_mongo[os.environ.get("DB_NAME", "soleia")]
    async with httpx.AsyncClient() as client:
        for c in cities:
            await process_city(c, db, client, dry_run)
    client_mongo.close()
    print(f"\n=== Done @ {datetime.now(timezone.utc).isoformat()} ===")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--city", nargs="+", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args.city or DEFAULT_CITIES, args.dry_run))
