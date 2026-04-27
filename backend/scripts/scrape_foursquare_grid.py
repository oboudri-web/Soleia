#!/usr/bin/env python3
"""
Soleia - Foursquare cell-grid scraper.

Découpe la bbox d'une ville en cellules carrées (par défaut 1.5 km × 1.5 km)
et interroge Foursquare pour rooftop/bar/cafe sur CHAQUE cellule. Cette
approche est plus exhaustive que l'arrondissement-based scraping car elle
ne saute aucune zone géographique (notamment les périphéries et zones
résidentielles peu denses).

Dédup global vs base existante par nom-normalisé + distance ≤ 50 m.

Usage:
    python3 scripts/scrape_foursquare_grid.py [--cities Lyon,Marseille,Nantes]
                                              [--types rooftop,bar,cafe]
                                              [--cell-km 1.5]
                                              [--max-per-cell 50]
                                              [--dry-run]
"""
from __future__ import annotations

import os
import sys
import time
import json
import math
import argparse
from pathlib import Path
from typing import Any, Dict, List

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

# Reuse helpers from main FSQ scraper
from scripts.scrape_foursquare import (  # noqa: E402
    FSQ_CATEGORY_GROUPS,
    fsq_search,
    fsq_photos,
    build_terrace_doc,
    is_duplicate,
    is_blacklisted,
    terraces as terraces_coll,
)

# ─── BBox des villes (intra-muros + 1ère couronne) ────────────────────────
CITY_BBOXES: Dict[str, Dict[str, float]] = {
    "Paris":       {"south": 48.815, "west":  2.225, "north": 48.905, "east":  2.470},
    "Lyon":        {"south": 45.700, "west":  4.770, "north": 45.805, "east":  4.920},
    "Marseille":   {"south": 43.210, "west":  5.290, "north": 43.370, "east":  5.520},
    "Bordeaux":    {"south": 44.790, "west": -0.660, "north": 44.900, "east": -0.530},
    "Nantes":      {"south": 47.170, "west": -1.620, "north": 47.280, "east": -1.480},
    "Toulouse":    {"south": 43.550, "west":  1.370, "north": 43.660, "east":  1.500},
    "Nice":        {"south": 43.640, "west":  7.200, "north": 43.760, "east":  7.340},
    "Montpellier": {"south": 43.560, "west":  3.810, "north": 43.680, "east":  3.930},
}


def grid_centers(bbox: Dict[str, float], cell_km: float) -> List[tuple[float, float]]:
    """Génère les centres des cellules carrées de cell_km × cell_km."""
    south, north = bbox["south"], bbox["north"]
    west,  east  = bbox["west"],  bbox["east"]
    mean_lat = (south + north) / 2.0
    d_lat = cell_km / 111.32                                    # 1° lat ≈ 111.32 km
    d_lng = cell_km / (111.32 * math.cos(math.radians(mean_lat)))
    centers: List[tuple[float, float]] = []
    lat = south + d_lat / 2.0
    while lat < north:
        lng = west + d_lng / 2.0
        while lng < east:
            centers.append((lat, lng))
            lng += d_lng
        lat += d_lat
    return centers


def scrape_grid(
    cities: List[str],
    types: List[str],
    cell_km: float,
    max_per_cell: int,
    dry_run: bool,
    sleep_s: float = 0.20,
) -> Dict[str, Any]:
    print(f"\n[GRID FSQ] cities={cities} types={types} cell={cell_km}km max_per_cell={max_per_cell}")
    print("[DEDUP] preloading existing names+coords from MongoDB…")
    existing_all = list(terraces_coll.find({}, {"name": 1, "lat": 1, "lng": 1, "_id": 0}))
    print(f"[DEDUP] {len(existing_all)} existing docs in DB\n")

    radius_m = int(cell_km * 1000 * 0.75)  # 75% of cell to overlap with neighbors

    summary: Dict[str, Any] = {"cities": {}, "total_inserted": 0, "total_dup": 0,
                                "total_blacklisted": 0, "total_cells": 0}

    for city in cities:
        bbox = CITY_BBOXES.get(city)
        if not bbox:
            print(f"[SKIP] no bbox for {city}")
            continue
        centers = grid_centers(bbox, cell_km)
        print(f"\n── {city} ── {len(centers)} cells, r={radius_m}m")
        city_inserted = city_dup = city_bl = 0
        for ci, (lat, lng) in enumerate(centers, 1):
            cell_inserted = 0
            for t in types:
                cats = FSQ_CATEGORY_GROUPS.get(t)
                if not cats:
                    continue
                cursor = None
                fetched = 0
                while fetched < max_per_cell:
                    results, cursor = fsq_search((lat, lng), radius_m, cats,
                                                  limit=50, cursor=cursor)
                    if not results:
                        break
                    for place in results:
                        name = place.get("name") or ""
                        if is_blacklisted(name):
                            city_bl += 1
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
                        cell_inserted += 1
                        fetched += 1
                        if fetched >= max_per_cell:
                            break
                    if not cursor or fetched >= max_per_cell:
                        break
                    time.sleep(sleep_s)
            if ci % 10 == 0 or cell_inserted > 0:
                print(f"   cell {ci:>3}/{len(centers)}  ({lat:.4f},{lng:.4f})  +{cell_inserted}  city_total={city_inserted}")
            time.sleep(sleep_s / 2)

        summary["cities"][city] = {"cells": len(centers), "inserted": city_inserted,
                                    "duplicates": city_dup, "blacklisted": city_bl}
        summary["total_cells"] += len(centers)
        summary["total_inserted"] += city_inserted
        summary["total_dup"] += city_dup
        summary["total_blacklisted"] += city_bl
        print(f"\n[CITY DONE] {city}: cells={len(centers)} +{city_inserted} new, dup={city_dup}, bl={city_bl}")

    print("\n" + "=" * 70)
    print("FINAL SUMMARY")
    print("=" * 70)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return summary


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--cities", default="Lyon,Marseille,Nantes")
    p.add_argument("--types", default="rooftop,bar,cafe")
    p.add_argument("--cell-km", type=float, default=1.5)
    p.add_argument("--max-per-cell", type=int, default=50)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    cities = [c.strip() for c in args.cities.split(",") if c.strip()]
    types  = [t.strip() for t in args.types.split(",")   if t.strip()]
    out = scrape_grid(cities, types, args.cell_km, args.max_per_cell, args.dry_run)
    log = SCRIPT_DIR / "scrape_foursquare_grid_last_run.json"
    log.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"\n[LOG] saved to {log}")


if __name__ == "__main__":
    main()
