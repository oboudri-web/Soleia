#!/usr/bin/env python3
"""
Soleia - Seed des établissements Paris open data NON matchés vs notre base.

Stratégie :
    1. Récupère les 23 796 records open-data terrasses-autorisations.paris.fr
    2. Pour chaque record : applique le matching multi-stratégies vs base existante.
       Si MATCH → SKIP (on ne touche jamais aux docs déjà en base, même si Google/FSQ).
    3. Si PAS de match → applique :
        a) Blacklist fast-food / chaînes (McDo, KFC, Subway, Starbucks, Paul…)
        b) Dédup stricte vs DB par nom normalisé + distance ≤ 50 m
        c) Enrichissement Foursquare (nom propre + photos + rating)
        d) Création nouveau doc avec opendata_source='paris', has_terrace_confirmed=True

Usage:
    python3 scripts/seed_opendata_paris.py [--limit N] [--no-fsq] [--dry-run]
"""
from __future__ import annotations

import os
import sys
import time
import math
import json
import uuid
import argparse
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv
from pymongo import MongoClient
import jellyfish

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

# Reuse helpers from import_opendata_terraces (matching algo)
from scripts.import_opendata_terraces import (  # noqa: E402
    DATASETS,
    fetch_all_records,
    get_geo,
    find_match,
    normalize_text,
    haversine_m,
)

load_dotenv(BACKEND_DIR / ".env")

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ.get("DB_NAME", "soleia")
db = MongoClient(MONGO_URL)[DB_NAME]
terraces = db.terraces

FSQ_KEY = os.environ.get("FOURSQUARE_API_KEY", "").strip()

# ─── Blacklist fast-food + chaînes (mots-clés case-insensitive) ───────────
BLACKLIST_PATTERNS = [
    r"mc\s*donald'?s?",
    r"\bkfc\b",
    r"burger\s*king",
    r"\bsubway\b",
    r"pizza\s*hut",
    r"domino'?s?",
    r"\bquick\b",
    r"five\s*guys",
    r"o'?tacos",
    r"\bkebab\b",
    r"bagelstein",
    r"brioche\s*dor[eé]e",
    r"\bpaul\b",
    r"starbucks",
    r"costa\s*coffee",
    r"tim\s*hortons",
    r"chipotle",
    r"taco\s*bell",
    r"wendy'?s?",
    r"prêt\s*[aà]\s*manger",
    r"cojean",
    r"class'?croute",
    r"columbus\s*caf[eé]",
    r"factory\s*&\s*co",
]
BLACKLIST_RE = re.compile("|".join(BLACKLIST_PATTERNS), flags=re.IGNORECASE)


def is_blacklisted(name: str) -> bool:
    return bool(BLACKLIST_RE.search(name or ""))


def title_case_clean(name: str) -> str:
    """Convert ALL CAPS or weird case to proper Title Case (FR-aware)."""
    if not name:
        return name
    n = name.strip()
    # Heuristic: if mostly upper, title-case; otherwise leave alone.
    upper_ratio = sum(1 for c in n if c.isupper()) / max(1, sum(1 for c in n if c.isalpha()))
    if upper_ratio > 0.5:
        # Title case but keep small words lowercase + handle apostrophes
        small = {"de", "du", "des", "le", "la", "les", "à", "au", "aux", "et", "en", "of", "and", "the", "d", "l"}
        words = re.split(r"(\s+|['-])", n.lower())
        out = []
        is_first = True
        for w in words:
            if not w.strip() or w in (" ", "'", "-"):
                out.append(w)
                continue
            if not is_first and w in small:
                out.append(w)
            else:
                out.append(w[:1].upper() + w[1:])
                is_first = False
        return "".join(out).strip()
    return n


# ─── Dedup utility (strict: name normalized + distance ≤ 50m) ─────────────
def is_strict_duplicate(name: str, lat: float, lng: float, existing: List[Dict[str, Any]]) -> bool:
    norm = normalize_text(name)
    if not norm:
        return False
    for e in existing:
        try:
            elat = float(e.get("lat") or 0)
            elng = float(e.get("lng") or 0)
        except (TypeError, ValueError):
            continue
        if haversine_m(lat, lng, elat, elng) > 50.0:
            continue
        ename = normalize_text(e.get("name") or "")
        if not ename:
            continue
        if ename == norm or ename in norm or norm in ename:
            return True
    return False


# ─── Foursquare enrichment ────────────────────────────────────────────────
FSQ_BASE = "https://places-api.foursquare.com"
FSQ_HEADERS = {
    "Accept": "application/json",
    "Authorization": f"Bearer {FSQ_KEY}",
    "X-Places-Api-Version": "2025-06-17",
}


def fsq_search_one(name: str, lat: float, lng: float) -> Optional[Dict[str, Any]]:
    """Find the best Foursquare match for (name, lat, lng) within 75m."""
    if not FSQ_KEY:
        return None
    try:
        params = {
            "query": name,
            "ll": f"{lat},{lng}",
            "radius": 75,
            "limit": 5,
            "sort": "DISTANCE",
        }
        r = requests.get(f"{FSQ_BASE}/places/search", headers=FSQ_HEADERS, params=params, timeout=12)
        if r.status_code != 200:
            return None
        results = (r.json() or {}).get("results") or []
        if not results:
            return None
        # First result is the closest by sort=DISTANCE
        return results[0]
    except Exception:
        return None


def fsq_photos(fsq_place_id: str, limit: int = 3) -> List[str]:
    if not FSQ_KEY or not fsq_place_id:
        return []
    try:
        r = requests.get(f"{FSQ_BASE}/places/{fsq_place_id}/photos",
                         headers=FSQ_HEADERS, params={"limit": limit}, timeout=10)
        if r.status_code != 200:
            return []
        return [f"{p.get('prefix','')}original{p.get('suffix','')}"
                for p in (r.json() or []) if p.get("prefix") and p.get("suffix")]
    except Exception:
        return []


# ─── Soleia → category mapping (Paris open-data → bar/cafe/restaurant) ────
def categorize(typo: Optional[str], fsq_categories: Optional[List[Dict[str, Any]]] = None) -> str:
    """Use FSQ category if available, else default to 'restaurant' (most common)."""
    if fsq_categories:
        cids = [str(c.get("fsq_category_id") or c.get("id") or "") for c in fsq_categories]
        # Reuse mapping from scrape_foursquare
        # Rooftop
        if "5f2c224bb6d05514c70440a3" in cids or "4bf58dd8d48988d133951735" in cids:
            return "rooftop"
        # Bars
        if any(c in cids for c in [
            "4bf58dd8d48988d116941735",  # Bar
            "4bf58dd8d48988d11e941735",  # Cocktail Bar
            "4bf58dd8d48988d1d5941735",  # Hotel Bar
            "4bf58dd8d48988d11b941735",  # Pub
            "4bf58dd8d48988d123941735",  # Wine Bar
        ]):
            return "bar"
        # Cafes
        if any(c in cids for c in [
            "4bf58dd8d48988d1e0931735",  # Coffee Shop
            "4bf58dd8d48988d16d941735",  # Café
            "4bf58dd8d48988d1dc931735",  # Tea Room
        ]):
            return "cafe"
    return "restaurant"


# ─── Main ─────────────────────────────────────────────────────────────────
def run(limit: Optional[int], use_fsq: bool, dry_run: bool):
    cfg = DATASETS["Paris"]
    print(f"=== SEED Paris open-data — limit={limit} use_fsq={use_fsq} dry_run={dry_run} ===\n")

    # Fetch open-data records
    records = fetch_all_records(cfg["base_url"], cfg["dataset_id"])
    print(f"  → {len(records)} open-data records fetched")

    # Pre-load existing DB candidates (Paris-area only for matching speed)
    candidates = list(
        terraces.find(
            {"city": "Paris"},
            {"id": 1, "name": 1, "lat": 1, "lng": 1, "address": 1, "_id": 0},
        )
    )
    print(f"  → {len(candidates)} existing Paris docs in DB\n")

    # For dedup via name+50m, we need the FULL DB (some open-data points may already
    # have been seeded under a sloppy name that doesn't match the official one).
    full_dedup_idx = list(
        terraces.find({}, {"name": 1, "lat": 1, "lng": 1, "_id": 0})
    )

    counts = {
        "total": 0,
        "skipped_match": 0,        # already in DB via fuzzy match
        "skipped_blacklist": 0,    # fast-food / chain
        "skipped_no_name": 0,
        "skipped_dedup": 0,        # name+50m strict
        "skipped_no_geo": 0,
        "fsq_enriched": 0,
        "inserted": 0,
    }

    for i, rec in enumerate(records):
        if limit and counts["inserted"] >= limit:
            print(f"\n[STOP] Reached --limit={limit}")
            break
        counts["total"] += 1
        name_raw = (rec.get(cfg["name_field"]) or "").strip()
        if not name_raw:
            counts["skipped_no_name"] += 1
            continue
        if is_blacklisted(name_raw):
            counts["skipped_blacklist"] += 1
            continue
        geo = get_geo(rec)
        if not geo:
            counts["skipped_no_geo"] += 1
            continue
        lat, lng = geo
        address = (rec.get(cfg["address_field"]) or "").strip()

        # Step 1 : already in DB via fuzzy match → skip
        existing = find_match(name_raw, lat, lng, address, candidates)
        if existing:
            counts["skipped_match"] += 1
            continue

        # Step 2 : strict name+50m dedup vs full DB
        if is_strict_duplicate(name_raw, lat, lng, full_dedup_idx):
            counts["skipped_dedup"] += 1
            continue

        # Step 3 : enrichment FSQ (rating, photos, real name, category)
        clean_name = title_case_clean(name_raw)
        photo_url = None
        photos: List[str] = []
        rating = None
        ratings_count = 0
        soleia_type = "restaurant"  # default for open-data Paris
        fsq_id = None
        if use_fsq:
            fsq = fsq_search_one(name_raw, lat, lng)
            if fsq:
                fsq_name = (fsq.get("name") or "").strip()
                if fsq_name:
                    clean_name = fsq_name  # FSQ name takes precedence
                fsq_id = fsq.get("fsq_place_id") or fsq.get("fsq_id")
                photos = fsq_photos(fsq_id) if fsq_id else []
                photo_url = photos[0] if photos else None
                raw_rating = fsq.get("rating")
                if isinstance(raw_rating, (int, float)):
                    rating = round(raw_rating / 2.0, 1)
                stats = fsq.get("stats") or {}
                ratings_count = (
                    stats.get("total_ratings")
                    or stats.get("total_tips")
                    or 0
                )
                soleia_type = categorize(rec.get("typologie"), fsq.get("categories"))
                counts["fsq_enriched"] += 1

        if not photo_url:
            photo_url = (
                "https://images.unsplash.com/photo-1574936145840-28808d77a0b6"
                "?w=600&auto=format&fit=crop"
            )

        # Re-blacklist on FSQ name (in case FSQ returned a different chain name)
        if is_blacklisted(clean_name):
            counts["skipped_blacklist"] += 1
            continue

        # Step 4 : build doc
        doc = {
            "id": str(uuid.uuid4()),
            "name": clean_name,
            "type": soleia_type,
            "city": "Paris",
            "lat": float(lat),
            "lng": float(lng),
            "address": address,
            "photo_url": photo_url,
            "photos": photos,
            "google_rating": rating,
            "google_ratings_count": int(ratings_count or 0),
            "google_maps_uri": None,
            "phone_number": None,
            "website_uri": None,
            "opening_hours": None,
            "terrace_source": "opendata",
            "opendata_source": "paris",
            "opendata_address": address,
            "opendata_typologie": rec.get("typologie"),
            "opendata_arrondissement": rec.get("arrondissement"),
            "opendata_longueur": rec.get("longueur"),
            "opendata_largeur": rec.get("largeur"),
            "foursquare_fsq_id": fsq_id,
            "has_terrace_confirmed": True,
            "shadow_analyzed": False,
            "ai_description": None,
            "orientation_degrees": 180.0,  # default Sud (will be refined later)
            "orientation_label": "Sud",
            "sun_status": "shade",
            "shadow_sunny_minutes": 0,
        }

        if not dry_run:
            terraces.insert_one(doc)
        # update in-memory dedup index so concurrent batches don't re-import
        full_dedup_idx.append({"name": doc["name"], "lat": doc["lat"], "lng": doc["lng"]})
        counts["inserted"] += 1
        if counts["inserted"] % 50 == 0:
            print(f"  +{counts['inserted']} inserted (records processed: {counts['total']}/{len(records)})")
        if use_fsq:
            time.sleep(0.25)  # FSQ rate-limit safety

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(json.dumps(counts, indent=2, ensure_ascii=False))
    log = SCRIPT_DIR / "seed_opendata_paris_last_run.json"
    log.write_text(json.dumps(counts, indent=2, ensure_ascii=False))
    print(f"\n[LOG] saved to {log}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=None, help="Max new inserts")
    p.add_argument("--no-fsq", action="store_true", help="Skip Foursquare enrichment")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    run(limit=args.limit, use_fsq=not args.no_fsq, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
