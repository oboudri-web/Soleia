#!/usr/bin/env python3
"""
Soleia - Décalage GPS 4m vers la terrasse, pour les docs SANS opendata_source.

Pour les villes/établissements qui n'ont pas de dataset open-data officiel
des terrasses (Lyon, Nantes, Bordeaux, Montpellier, Nice, Marseille — ainsi
que les docs Paris/Toulouse non matchés), on simule la position de la terrasse
en décalant la coordonnée GPS de l'établissement de 4 mètres dans la direction
indiquée par `orientation_degrees`.

Convention de bearing :
    0°   = nord  (terrasse au nord du resto)
    90°  = est
    180° = sud   (par défaut FSQ — orientation la plus courante en France)
    270° = ouest

Mécanisme :
    delta_north_m = cos(bearing) * 4
    delta_east_m  = sin(bearing) * 4
    lat += delta_north_m / 111_320
    lng += delta_east_m  / (111_320 * cos(lat_rad))

Sécurité :
    - On ne touche JAMAIS aux docs avec opendata_source (= coords officielles
      de la terrasse sur la voie publique).
    - On stocke les coords originales dans `original_lat`/`original_lng` pour
      pouvoir réverser si besoin.
    - On flagge `gps_offset_applied=True`.

Usage:
    python3 scripts/offset_gps_to_terrace.py [--cities Lyon,Nantes] [--dry-run]
"""
from __future__ import annotations

import os
import sys
import math
import json
import argparse
from pathlib import Path

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
db = MongoClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "soleia")]
terraces = db.terraces

OFFSET_M = 4.0
DEFAULT_BEARING = 180.0  # Sud par défaut si orientation_degrees absent


def offset_coords(lat: float, lng: float, bearing_deg: float, dist_m: float = OFFSET_M):
    brng = math.radians(bearing_deg)
    dn = math.cos(brng) * dist_m
    de = math.sin(brng) * dist_m
    new_lat = lat + dn / 111_320.0
    new_lng = lng + de / (111_320.0 * math.cos(math.radians(lat)))
    return new_lat, new_lng


def run(cities: list, dry_run: bool):
    # Build the query : docs without opendata_source AND not yet offset
    query = {
        "opendata_source": {"$exists": False},
        "gps_offset_applied": {"$ne": True},
    }
    if cities:
        query["city"] = {"$in": cities}

    cur = terraces.find(query, {
        "id": 1, "name": 1, "city": 1, "lat": 1, "lng": 1,
        "orientation_degrees": 1, "_id": 0,
    })
    docs = list(cur)
    print(f"[INFO] {len(docs)} docs to offset (filter: cities={cities or 'ALL'}, no opendata_source, no gps_offset_applied)")

    by_city = {}
    updated = 0
    for d in docs:
        try:
            lat = float(d["lat"])
            lng = float(d["lng"])
        except (KeyError, TypeError, ValueError):
            continue
        bearing = float(d.get("orientation_degrees") or DEFAULT_BEARING)
        new_lat, new_lng = offset_coords(lat, lng, bearing)
        if not dry_run:
            terraces.update_one({"id": d["id"]}, {
                "$set": {
                    "lat": new_lat,
                    "lng": new_lng,
                    "original_lat": lat,
                    "original_lng": lng,
                    "gps_offset_applied": True,
                    "gps_offset_meters": OFFSET_M,
                    "gps_offset_bearing": bearing,
                },
            })
        updated += 1
        c = d.get("city") or "?"
        by_city[c] = by_city.get(c, 0) + 1

    print(f"\n[DONE] Offset applied to {updated} docs (dry_run={dry_run})")
    print("\nPer-city breakdown :")
    for c, n in sorted(by_city.items(), key=lambda x: -x[1]):
        print(f"  {c:<14} {n:>5}")

    log = Path(__file__).resolve().parent / "offset_gps_last_run.json"
    log.write_text(json.dumps({
        "total_offset": updated,
        "by_city": by_city,
        "dry_run": dry_run,
    }, indent=2, ensure_ascii=False))
    print(f"\n[LOG] saved to {log}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--cities", default="", help="Comma-separated city list (default: ALL)")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    cities = [c.strip() for c in args.cities.split(",") if c.strip()]
    run(cities, args.dry_run)


if __name__ == "__main__":
    main()
