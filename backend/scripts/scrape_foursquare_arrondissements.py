#!/usr/bin/env python3
"""
Soleia - Foursquare scraper PAR ARRONDISSEMENTS / SOUS-ZONES.

Étend scrape_foursquare.py en découpant Paris (20 arr.), Lyon (9 arr.)
et Marseille (16 arr.) en sous-zones de rayon 1000-1200m. Chaque
sous-zone est interrogée pour rooftop+bar+cafe, avec dédup global vs
la base existante.

Usage:
    python3 scripts/scrape_foursquare_arrondissements.py [--cities Paris,Lyon,Marseille]
                                                        [--types rooftop,bar,cafe]
                                                        [--radius 1100]
                                                        [--max-per-zone 80]
                                                        [--dry-run]

Le script importe les helpers du scraper principal (fsq_search, fsq_photos,
build_terrace_doc, is_duplicate, …) pour rester DRY.
"""
from __future__ import annotations

import os
import sys
import time
import json
import argparse
from pathlib import Path
from typing import Any, Dict, List

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

# Reuse helpers from main scraper
from scripts.scrape_foursquare import (  # noqa: E402
    FSQ_CATEGORY_GROUPS,
    fsq_search,
    fsq_photos,
    build_terrace_doc,
    is_duplicate,
    is_blacklisted,
    terraces as terraces_coll,
)

# ─── Sous-zones (centroides) ──────────────────────────────────────────────
# Paris : 20 arrondissements (centroides approximatifs)
PARIS_ARR: List[Dict[str, Any]] = [
    {"name": "Paris-1",  "lat": 48.8635, "lng": 2.3360},
    {"name": "Paris-2",  "lat": 48.8676, "lng": 2.3422},
    {"name": "Paris-3",  "lat": 48.8631, "lng": 2.3625},
    {"name": "Paris-4",  "lat": 48.8546, "lng": 2.3576},
    {"name": "Paris-5",  "lat": 48.8447, "lng": 2.3498},
    {"name": "Paris-6",  "lat": 48.8506, "lng": 2.3329},
    {"name": "Paris-7",  "lat": 48.8561, "lng": 2.3120},
    {"name": "Paris-8",  "lat": 48.8722, "lng": 2.3122},
    {"name": "Paris-9",  "lat": 48.8769, "lng": 2.3372},
    {"name": "Paris-10", "lat": 48.8761, "lng": 2.3608},
    {"name": "Paris-11", "lat": 48.8593, "lng": 2.3795},
    {"name": "Paris-12", "lat": 48.8408, "lng": 2.3876},
    {"name": "Paris-13", "lat": 48.8322, "lng": 2.3563},
    {"name": "Paris-14", "lat": 48.8331, "lng": 2.3265},
    {"name": "Paris-15", "lat": 48.8410, "lng": 2.2992},
    {"name": "Paris-16", "lat": 48.8595, "lng": 2.2725},
    {"name": "Paris-17", "lat": 48.8869, "lng": 2.3066},
    {"name": "Paris-18", "lat": 48.8925, "lng": 2.3490},
    {"name": "Paris-19", "lat": 48.8839, "lng": 2.3838},
    {"name": "Paris-20", "lat": 48.8631, "lng": 2.3994},
]

# Lyon : 9 arrondissements
LYON_ARR: List[Dict[str, Any]] = [
    {"name": "Lyon-1", "lat": 45.7691, "lng": 4.8347},
    {"name": "Lyon-2", "lat": 45.7508, "lng": 4.8286},
    {"name": "Lyon-3", "lat": 45.7589, "lng": 4.8542},
    {"name": "Lyon-4", "lat": 45.7775, "lng": 4.8226},
    {"name": "Lyon-5", "lat": 45.7611, "lng": 4.8155},
    {"name": "Lyon-6", "lat": 45.7716, "lng": 4.8505},
    {"name": "Lyon-7", "lat": 45.7411, "lng": 4.8408},
    {"name": "Lyon-8", "lat": 45.7349, "lng": 4.8675},
    {"name": "Lyon-9", "lat": 45.7717, "lng": 4.8056},
]

# Marseille : 16 arrondissements (centroides)
MARSEILLE_ARR: List[Dict[str, Any]] = [
    {"name": "Marseille-1",  "lat": 43.2967, "lng": 5.3819},
    {"name": "Marseille-2",  "lat": 43.3066, "lng": 5.3623},
    {"name": "Marseille-3",  "lat": 43.3167, "lng": 5.3845},
    {"name": "Marseille-4",  "lat": 43.3091, "lng": 5.4065},
    {"name": "Marseille-5",  "lat": 43.2916, "lng": 5.4022},
    {"name": "Marseille-6",  "lat": 43.2856, "lng": 5.3851},
    {"name": "Marseille-7",  "lat": 43.2854, "lng": 5.3617},
    {"name": "Marseille-8",  "lat": 43.2655, "lng": 5.3855},
    {"name": "Marseille-9",  "lat": 43.2548, "lng": 5.4360},
    {"name": "Marseille-10", "lat": 43.2802, "lng": 5.4170},
    {"name": "Marseille-11", "lat": 43.2810, "lng": 5.4660},
    {"name": "Marseille-12", "lat": 43.2961, "lng": 5.4378},
    {"name": "Marseille-13", "lat": 43.3245, "lng": 5.4264},
    {"name": "Marseille-14", "lat": 43.3411, "lng": 5.4029},
    {"name": "Marseille-15", "lat": 43.3500, "lng": 5.3729},
    {"name": "Marseille-16", "lat": 43.3611, "lng": 5.3438},
]

CITY_TO_ARR: Dict[str, List[Dict[str, Any]]] = {
    "Paris": PARIS_ARR,
    "Lyon": LYON_ARR,
    "Marseille": MARSEILLE_ARR,
}


def scrape_arrondissements(
    cities: List[str],
    types: List[str],
    radius_m: int,
    max_per_zone: int,
    dry_run: bool,
    sleep_s: float = 0.25,
) -> Dict[str, Any]:
    print(f"\n[START] FSQ ARRONDISSEMENTS — cities={cities} types={types} r={radius_m}m max_per_zone={max_per_zone}\n")
    print("[DEDUP] loading existing names+coords from MongoDB…")
    existing_all = list(terraces_coll.find({}, {"name": 1, "lat": 1, "lng": 1, "_id": 0}))
    print(f"[DEDUP] {len(existing_all)} existing docs in DB\n")

    summary: Dict[str, Any] = {"cities": {}, "total_inserted": 0, "total_dup": 0, "total_blacklisted": 0}

    for city in cities:
        zones = CITY_TO_ARR.get(city)
        if not zones:
            print(f"[SKIP] no arrondissements defined for {city}")
            continue

        city_inserted = city_dup = city_blacklist = 0
        for zone in zones:
            ll = (zone["lat"], zone["lng"])
            zone_ins = 0
            for t in types:
                cats = FSQ_CATEGORY_GROUPS.get(t)
                if not cats:
                    continue
                page = 0
                cursor = None
                while True:
                    page += 1
                    results, cursor = fsq_search(ll, radius_m, cats, limit=50, cursor=cursor)
                    if not results:
                        break
                    for place in results:
                        name = place.get("name") or ""
                        if is_blacklisted(name):
                            city_blacklist += 1
                            continue
                        plat = place.get("latitude") or (place.get("geocodes") or {}).get("main", {}).get("latitude")
                        plng = place.get("longitude") or (place.get("geocodes") or {}).get("main", {}).get("longitude")
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
                            terraces_coll.insert_one(doc)
                        existing_all.append({"name": doc["name"], "lat": doc["lat"], "lng": doc["lng"]})
                        city_inserted += 1
                        zone_ins += 1
                        if zone_ins >= max_per_zone:
                            break
                        time.sleep(sleep_s / 4)
                    if zone_ins >= max_per_zone:
                        break
                    if not cursor:
                        break
                    time.sleep(sleep_s)
                if zone_ins >= max_per_zone:
                    break
            print(f"  {zone['name']:<14} +{zone_ins:>3} new (city total now {city_inserted})")

        summary["cities"][city] = {"inserted": city_inserted, "duplicates": city_dup, "blacklisted": city_blacklist}
        summary["total_inserted"] += city_inserted
        summary["total_dup"] += city_dup
        summary["total_blacklisted"] += city_blacklist
        print(f"\n[CITY DONE] {city}: inserted={city_inserted} dup={city_dup} blacklisted={city_blacklist}\n")

    print("=" * 70)
    print("FINAL SUMMARY")
    print("=" * 70)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return summary


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--cities", default="Paris,Lyon,Marseille")
    p.add_argument("--types", default="rooftop,bar,cafe")
    p.add_argument("--radius", type=int, default=1100)
    p.add_argument("--max-per-zone", type=int, default=80)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    cities = [c.strip() for c in args.cities.split(",") if c.strip()]
    types = [t.strip() for t in args.types.split(",") if t.strip()]
    out = scrape_arrondissements(cities, types, args.radius, args.max_per_zone, args.dry_run)
    log = SCRIPT_DIR / "scrape_foursquare_arr_last_run.json"
    log.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"\n[LOG] saved to {log}")


if __name__ == "__main__":
    main()
