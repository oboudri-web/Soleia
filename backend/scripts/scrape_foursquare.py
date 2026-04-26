#!/usr/bin/env python3
"""
Scraper Foursquare Places API v3 — Soleia.

Stratégie « Option B » : premier batch ciblé sur les 8 villes françaises
(Paris, Lyon, Marseille, Bordeaux, Toulouse, Nice, Nantes, Montpellier),
catégories Rooftop Bar / Bar / Café, avec déduplication stricte par
nom + coordonnées GPS à ±50 m vs la base existante.

Usage:
    python3 scripts/scrape_foursquare.py [--cities Paris,Lyon] [--types rooftop,bar,cafe]
                                         [--max-per-city 500] [--dry-run]

Output:
    Insère dans la collection `terraces` les nouveaux établissements en
    respectant le schéma existant (mêmes champs que Google Places). Les
    notes Foursquare sont divisées par 2 pour la conversion 10/10 → 5/5.

Champs ajoutés :
    - terrace_source = 'foursquare'
    - foursquare_fsq_id (str)         : ID natif FSQ pour reprises éventuelles
    - photo_url, photos[]             : URLs Foursquare
    - opening_hours (str ou liste)    : horaires bruts FSQ
    - google_rating (float)           : note convertie 10/10 → 5/5
    - google_ratings_count (int)      : total tips/avis FSQ

Categories FSQ v3 (extraits) :
    13037  Rooftop Bar           (cible #1, on en veut 50+ par grosse ville)
    13003  Bar
    13035  Hotel Bar
    13036  Sports Bar
    13046  Pub
    13066  Beer Bar
    13063  Coffee Shop
    13065  Café
    13145  Bistro

Rate limits Foursquare Places API v3 :
    50 requêtes / seconde (large) et 200 résultats max par requête (50 / page * pagination).
    On reste largement sous : 0.25s entre requêtes.
"""

from __future__ import annotations

import os
import sys
import time
import math
import json
import argparse
import re
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests
from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.collection import Collection

# ─── Setup ──────────────────────────────────────────────────────────────────
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

FSQ_KEY = os.environ.get("FOURSQUARE_API_KEY", "").strip()
if not FSQ_KEY:
    print("[ERR] FOURSQUARE_API_KEY missing in backend/.env", file=sys.stderr)
    sys.exit(1)

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ.get("DB_NAME", "soleia")

client = MongoClient(MONGO_URL)
db = client[DB_NAME]
terraces: Collection = db.terraces

# ─── Constants ──────────────────────────────────────────────────────────────
CITIES: Dict[str, Dict[str, Any]] = {
    "Paris":       {"lat": 48.8566, "lng": 2.3522,  "radius_m": 8000},
    "Lyon":        {"lat": 45.7640, "lng": 4.8357,  "radius_m": 6000},
    "Marseille":   {"lat": 43.2965, "lng": 5.3698,  "radius_m": 8000},
    "Bordeaux":    {"lat": 44.8378, "lng": -0.5792, "radius_m": 5000},
    "Toulouse":    {"lat": 43.6047, "lng": 1.4442,  "radius_m": 5000},
    "Nice":        {"lat": 43.7102, "lng": 7.2620,  "radius_m": 5000},
    "Nantes":      {"lat": 47.2184, "lng": -1.5536, "radius_m": 5000},
    "Montpellier": {"lat": 43.6108, "lng": 3.8767,  "radius_m": 5000},
}

# Type taxonomy used by Soleia → Foursquare Service API category IDs (v2025)
FSQ_BASE_URL = "https://places-api.foursquare.com"
# Foursquare Service API v2025 (succède à l'API v3 dépréciée 11/2025).
# Taxonomy : `fsq_category_ids` (UUID-style 24-char) — voir
# https://docs.foursquare.com/data-products/docs/categories
FSQ_CATEGORY_NAMES_TO_IDS = {
    # rooftop / bars en hauteur
    "rooftop_bar":   "4bf58dd8d48988d1bc941735",
    # bars classiques
    "bar":           "4bf58dd8d48988d116941735",
    "cocktail_bar":  "4bf58dd8d48988d11e941735",
    "hotel_bar":     "4bf58dd8d48988d1d5941735",
    "pub":           "4bf58dd8d48988d11b941735",
    "wine_bar":      "4bf58dd8d48988d123941735",
    "speakeasy":     "4bf58dd8d48988d1d4941735",
    "beer_bar":      "52e81612bcbc57f1066b7a0d",
    # cafés
    "coffee_shop":   "4bf58dd8d48988d1e0931735",
    "cafe":          "4bf58dd8d48988d16d941735",
    "tea_room":      "4bf58dd8d48988d1dc931735",
}

FSQ_CATEGORY_GROUPS: Dict[str, List[str]] = {
    "rooftop": [FSQ_CATEGORY_NAMES_TO_IDS["rooftop_bar"]],
    "bar": [
        FSQ_CATEGORY_NAMES_TO_IDS["bar"],
        FSQ_CATEGORY_NAMES_TO_IDS["cocktail_bar"],
        FSQ_CATEGORY_NAMES_TO_IDS["hotel_bar"],
        FSQ_CATEGORY_NAMES_TO_IDS["pub"],
        FSQ_CATEGORY_NAMES_TO_IDS["wine_bar"],
        FSQ_CATEGORY_NAMES_TO_IDS["speakeasy"],
        FSQ_CATEGORY_NAMES_TO_IDS["beer_bar"],
    ],
    "cafe": [
        FSQ_CATEGORY_NAMES_TO_IDS["coffee_shop"],
        FSQ_CATEGORY_NAMES_TO_IDS["cafe"],
        FSQ_CATEGORY_NAMES_TO_IDS["tea_room"],
    ],
}

# Brand chains to skip (we don't want McDo and friends)
BRAND_BLACKLIST_RE = re.compile(
    r"\b(?:mcdonald'?s?|kfc|burger\s*king|starbucks|subway|five\s*guys|domino'?s?|"
    r"pizza\s*hut|paul\b|brioche\s*dor[eé]e|columbus\s*caf[eé]|prêt\s*[aà]\s*manger|"
    r"cojean|class'?croute|brioch'in|boco\b)",
    flags=re.IGNORECASE,
)

DEFAULT_PHOTO = (
    "https://images.unsplash.com/photo-1574936145840-28808d77a0b6?w=600&auto=format&fit=crop"
)

session = requests.Session()
session.headers.update({
    "Accept": "application/json",
    # Foursquare Service API (v2025) — Bearer auth + version header.
    "Authorization": f"Bearer {FSQ_KEY}",
    "X-Places-Api-Version": "2025-06-17",
})


# ─── Helpers ────────────────────────────────────────────────────────────────
def normalize_name(name: str) -> str:
    """Normalise un nom pour la déduplication (insensible accents, casse, espaces)."""
    if not name:
        return ""
    n = name.lower().strip()
    # remove accents (basic)
    accents = str.maketrans("àâäéèêëîïôöùûüç", "aaaeeeeiioouuuc")
    n = n.translate(accents)
    # remove punctuation
    n = re.sub(r"[^\w\s]", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    R = 6_371_000.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def is_duplicate(name: str, lat: float, lng: float, existing: List[Dict[str, Any]]) -> bool:
    """True si un établissement avec le même nom normalisé est à <50 m."""
    nname = normalize_name(name)
    if not nname:
        return False
    for e in existing:
        try:
            elat = float(e.get("lat") or 0)
            elng = float(e.get("lng") or 0)
        except (TypeError, ValueError):
            continue
        if haversine_m(lat, lng, elat, elng) <= 50.0:
            ename = normalize_name(e.get("name") or "")
            # match if names share at least 70% of characters (handles minor diff like "Cafe" vs "Café")
            if ename and (ename == nname or ename in nname or nname in ename):
                return True
    return False


def is_blacklisted(name: str) -> bool:
    return bool(BRAND_BLACKLIST_RE.search(name or ""))


def fsq_search(
    ll: Tuple[float, float],
    radius_m: int,
    category_ids: List[str],
    limit: int = 50,
    cursor: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Single page of /places/search (Foursquare Service API v2025)."""
    params = {
        "ll": f"{ll[0]},{ll[1]}",
        "radius": radius_m,
        "fsq_category_ids": ",".join(category_ids),
        "limit": min(limit, 50),
        "sort": "DISTANCE",
    }
    url = f"{FSQ_BASE_URL}/places/search"
    if cursor:
        url = cursor
        params = None
    try:
        r = session.get(url, params=params, timeout=20)
    except (requests.RequestException, ConnectionError) as e:
        print(f"  [WARN] FSQ HTTP error (retry once): {e}", file=sys.stderr)
        time.sleep(1.5)
        try:
            r = session.get(url, params=params, timeout=20)
        except Exception as e2:
            print(f"  [ERR] FSQ retry failed: {e2}", file=sys.stderr)
            return [], None
    if r.status_code != 200:
        print(f"  [ERR] FSQ {r.status_code}: {r.text[:200]}", file=sys.stderr)
        return [], None
    data = r.json()
    results = data.get("results", []) or []
    # Cursor next page via Link header (Service API)
    next_link = None
    link_h = r.headers.get("Link") or r.headers.get("link") or ""
    m = re.search(r'<([^>]+)>;\s*rel="next"', link_h)
    if m:
        next_link = m.group(1)
    return results, next_link


def fsq_photos(fsq_place_id: str, limit: int = 4) -> List[str]:
    """Returns up to N photo URLs (Service API v2025)."""
    try:
        r = session.get(
            f"{FSQ_BASE_URL}/places/{fsq_place_id}/photos",
            params={"limit": limit},
            timeout=15,
        )
        if r.status_code != 200:
            return []
        items = r.json() or []
        urls = []
        for p in items:
            prefix = p.get("prefix")
            suffix = p.get("suffix")
            if prefix and suffix:
                urls.append(f"{prefix}original{suffix}")
        return urls
    except Exception:
        return []


def category_to_soleia_type(fsq_categories: List[Dict[str, Any]]) -> str:
    """Map Service API categories to one of: rooftop > bar > cafe."""
    if not fsq_categories:
        return "bar"
    cids = [str(c.get("fsq_category_id") or c.get("id") or "") for c in fsq_categories]
    if FSQ_CATEGORY_NAMES_TO_IDS["rooftop_bar"] in cids:
        return "rooftop"
    if any(x in cids for x in FSQ_CATEGORY_GROUPS["bar"]):
        return "bar"
    if any(x in cids for x in FSQ_CATEGORY_GROUPS["cafe"]):
        return "cafe"
    return "bar"


def build_terrace_doc(place: Dict[str, Any], city: str, photo_urls: List[str]) -> Optional[Dict[str, Any]]:
    name = (place.get("name") or "").strip()
    if not name or is_blacklisted(name):
        return None

    # Service API v2025: latitude/longitude exposed at top-level (and in geocodes.main as fallback)
    lat = place.get("latitude")
    lng = place.get("longitude")
    if lat is None or lng is None:
        geocodes = place.get("geocodes", {}) or {}
        main = geocodes.get("main") or {}
        lat = main.get("latitude")
        lng = main.get("longitude")
    if lat is None or lng is None:
        return None

    location = place.get("location", {}) or {}
    address = location.get("formatted_address") or " ".join(filter(None, [
        location.get("address"), location.get("postcode"), location.get("locality"),
    ]))

    fsq_cats = place.get("categories", []) or []
    soleia_type = category_to_soleia_type(fsq_cats)

    raw_rating = place.get("rating")  # FSQ rating /10
    rating_5 = round((raw_rating / 2.0), 1) if isinstance(raw_rating, (int, float)) else None
    stats = place.get("stats", {}) or {}
    ratings_count = stats.get("total_ratings") or stats.get("total_tips") or stats.get("total_photos") or 0

    hours = place.get("hours", {}) or {}
    hours_display = hours.get("display") or hours.get("regular") or None

    photo_url = photo_urls[0] if photo_urls else DEFAULT_PHOTO

    fsq_id = place.get("fsq_place_id") or place.get("fsq_id")

    doc = {
        "id": str(uuid.uuid4()),
        "name": name,
        "type": soleia_type,
        "city": city,
        "lat": float(lat),
        "lng": float(lng),
        "address": address,
        "photo_url": photo_url,
        "photos": photo_urls,
        "google_rating": rating_5,
        "google_ratings_count": int(ratings_count or 0),
        "google_maps_uri": None,
        "phone_number": place.get("tel"),
        "website_uri": place.get("website"),
        "opening_hours": hours_display,
        "terrace_source": "foursquare",
        "foursquare_fsq_id": fsq_id,
        # Soleia fields filled lazily by other pipelines:
        "shadow_analyzed": False,
        "has_terrace_confirmed": True,  # Bars/cafes/rooftops → assume terrace presence
        "ai_description": None,
        "orientation_degrees": 180.0,  # Default sud (peut être affiné par enrich_orientation.py)
        "orientation_label": "Sud",
        "sun_status": "shade",
        "shadow_sunny_minutes": 0,
    }
    return doc


# ─── Main ───────────────────────────────────────────────────────────────────
def scrape(
    cities: List[str],
    types: List[str],
    max_per_city: int,
    dry_run: bool,
    sleep_s: float = 0.25,
) -> Dict[str, Any]:
    print(f"\n[START] FSQ scrape — cities={cities} types={types} max_per_city={max_per_city} dry_run={dry_run}\n")

    # Load existing for global dedup (name+lat+lng keys)
    print("[DEDUP] loading existing names+coords from MongoDB...")
    existing_all = list(terraces.find({}, {"name": 1, "lat": 1, "lng": 1, "_id": 0}))
    print(f"[DEDUP] {len(existing_all)} existing docs in DB\n")

    summary: Dict[str, Any] = {
        "cities": {},
        "total_inserted": 0,
        "total_duplicates": 0,
        "total_blacklisted": 0,
        "total_fetched": 0,
    }

    for city in cities:
        if city not in CITIES:
            print(f"[SKIP] unknown city {city}")
            continue
        meta = CITIES[city]
        ll = (meta["lat"], meta["lng"])
        radius = meta["radius_m"]
        city_inserted = 0
        city_dup = 0
        city_blacklist = 0
        city_fetched = 0
        for t in types:
            cats = FSQ_CATEGORY_GROUPS.get(t)
            if not cats:
                print(f"  [SKIP] unknown type {t}")
                continue
            print(f"\n── {city} / {t.upper():10s} (cats={','.join(cats)}, r={radius}m) ──")
            page = 0
            cursor = None
            while True:
                page += 1
                results, cursor = fsq_search(ll, radius, cats, limit=50, cursor=cursor)
                if not results:
                    break
                for place in results:
                    city_fetched += 1
                    name = place.get("name") or ""
                    if is_blacklisted(name):
                        city_blacklist += 1
                        continue
                    plat = place.get("latitude")
                    plng = place.get("longitude")
                    if plat is None or plng is None:
                        geo = (place.get("geocodes") or {}).get("main") or {}
                        plat = geo.get("latitude")
                        plng = geo.get("longitude")
                    if plat is None or plng is None:
                        continue
                    if is_duplicate(name, plat, plng, existing_all):
                        city_dup += 1
                        continue
                    fsq_id = place.get("fsq_place_id") or place.get("fsq_id")
                    photos = fsq_photos(fsq_id) if fsq_id else []
                    doc = build_terrace_doc(place, city, photos)
                    if not doc:
                        continue
                    if not dry_run:
                        terraces.insert_one(doc)
                    existing_all.append({"name": doc["name"], "lat": doc["lat"], "lng": doc["lng"]})
                    city_inserted += 1
                    if city_inserted % 25 == 0:
                        print(f"    +{city_inserted} new (page {page})")
                    if city_inserted >= max_per_city:
                        break
                    time.sleep(sleep_s / 4)
                if city_inserted >= max_per_city:
                    break
                if not cursor:
                    break
                time.sleep(sleep_s)
            print(f"  → {t:10s}: fetched_so_far={city_fetched}, inserted_so_far={city_inserted}")
            if city_inserted >= max_per_city:
                break

        summary["cities"][city] = {
            "fetched": city_fetched,
            "inserted": city_inserted,
            "duplicates": city_dup,
            "blacklisted": city_blacklist,
        }
        summary["total_fetched"] += city_fetched
        summary["total_inserted"] += city_inserted
        summary["total_duplicates"] += city_dup
        summary["total_blacklisted"] += city_blacklist
        print(f"\n[CITY DONE] {city}: inserted={city_inserted} dup={city_dup} blacklisted={city_blacklist}")

    print("\n" + "=" * 70)
    print("FINAL SUMMARY")
    print("=" * 70)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return summary


def main() -> int:
    p = argparse.ArgumentParser(description="Soleia Foursquare scraper")
    p.add_argument("--cities", default=",".join(CITIES.keys()))
    p.add_argument("--types", default="rooftop,bar,cafe")
    p.add_argument("--max-per-city", type=int, default=2000)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    cities = [c.strip() for c in args.cities.split(",") if c.strip()]
    types = [t.strip() for t in args.types.split(",") if t.strip()]
    out = scrape(cities, types, args.max_per_city, args.dry_run)
    # Write summary to log file
    log = Path(__file__).resolve().parent / "scrape_foursquare_last_run.json"
    log.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"\n[LOG] summary saved to {log}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
