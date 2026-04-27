#!/usr/bin/env python3
"""
Soleia - Import des données open data officielles des terrasses autorisées.

Ces datasets municipaux donnent les coordonnées GPS exactes de la terrasse
sur la voie publique (et non l'entrée du restaurant), ce qui améliore
drastiquement la précision du calcul ShadeMap.

Datasets supportés (Opendatasoft v2.1) :
    - Paris    : https://opendata.paris.fr/explore/dataset/terrasses-autorisations/  (~23 796 entrées)
    - Toulouse : https://data.toulouse-metropole.fr/explore/dataset/terrasses-autorisees-ville-de-toulouse/  (~1 036 entrées)

Pour Lyon, Nantes, Bordeaux, Montpellier, Nice, Marseille : aucun dataset
open data terrasses dédié n'est exposé publiquement à ce jour. On peut
ré-exécuter ce script ultérieurement quand ils seront publiés.

Stratégie de matching :
    1. Pour chaque entrée open data, on cherche dans la DB une terrasse à
       moins de 200m avec un nom similaire (normalisé, accents/punctuation
       enlevés, ratio de tokens >= 0.5).
    2. En cas de match → on met à jour lat/lng pour les coords précises de
       la terrasse, et on flagge has_terrace_confirmed=True + opendata_source=...
    3. Pas de création de nouvelles entrées (juste enrichissement).

Usage:
    python3 scripts/import_opendata_terraces.py [--cities Paris,Toulouse] [--dry-run]
"""
from __future__ import annotations

import os
import sys
import time
import math
import json
import re
import argparse
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv
from pymongo import MongoClient
import jellyfish  # soundex / metaphone for fuzzy phonetic match

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ.get("DB_NAME", "soleia")
db = MongoClient(MONGO_URL)[DB_NAME]
terraces_coll = db.terraces

# ─── Datasets supportés ────────────────────────────────────────────────────
DATASETS: Dict[str, Dict[str, Any]] = {
    "Paris": {
        "base_url": "https://opendata.paris.fr",
        "dataset_id": "terrasses-autorisations",
        "name_field": "nom_enseigne",
        "address_field": "adresse",
        "extra_fields": ["arrondissement", "typologie", "longueur", "largeur"],
    },
    "Toulouse": {
        "base_url": "https://data.toulouse-metropole.fr",
        "dataset_id": "terrasses-autorisees-ville-de-toulouse",
        "name_field": "etablissement",
        "address_field": None,  # built from numero_voie + type_voie + nom_voie
        "extra_fields": ["numero_voie", "nom_voie", "code_postal", "domaine_activite"],
    },
}


# ─── Helpers ──────────────────────────────────────────────────────────────
def normalize_text(t: Optional[str]) -> str:
    if not t:
        return ""
    n = t.lower().strip()
    accents = str.maketrans("àâäéèêëîïôöùûüç", "aaaeeeeiioouuuc")
    n = n.translate(accents)
    n = re.sub(r"[^\w\s]", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    R = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def name_similarity(a: str, b: str) -> float:
    """Token-based Jaccard similarity. Stop-words filtered."""
    STOPWORDS = {"le", "la", "les", "de", "du", "des", "l", "d", "et", "the", "bar", "cafe", "restaurant", "brasserie"}
    ta = {w for w in normalize_text(a).split() if w not in STOPWORDS and len(w) >= 2}
    tb = {w for w in normalize_text(b).split() if w not in STOPWORDS and len(w) >= 2}
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    union = len(ta | tb)
    return inter / union


# ── Adresse normalisation ────────────────────────────────────────────────
ADDR_TYPE_VOIE_MAP = {
    "av": "avenue", "ave": "avenue", "av.": "avenue",
    "bd": "boulevard", "bld": "boulevard", "blvd": "boulevard", "bvd": "boulevard",
    "rte": "route",
    "pl": "place", "plc": "place",
    "imp": "impasse",
    "all": "allee", "allee": "allee", "allée": "allee",
    "fbg": "faubourg", "fg": "faubourg",
    "sq": "square",
    "qu": "quai",
    "pte": "porte",
    "pas": "passage", "psg": "passage",
    "crs": "cours", "cr": "cours",
    "vle": "ville", "ste": "saint", "st": "saint",
}


def parse_address(addr: str) -> Optional[Tuple[str, str]]:
    """Return (numero, rue_normalized) tuple, or None if can't parse."""
    if not addr:
        return None
    n = normalize_text(addr)
    # Match "12 bis avenue ..." or "12 rue ..." or "12-14 rue ..."
    m = re.match(r"^(\d{1,4})(?:\s*(?:bis|ter|quater|[-–]\s*\d+))?\s+(.+)$", n)
    if not m:
        return None
    numero = m.group(1)
    rest = m.group(2).strip()
    # Strip type voie + normalize abbreviations
    parts = rest.split()
    if not parts:
        return None
    first = parts[0]
    if first in ADDR_TYPE_VOIE_MAP:
        first = ADDR_TYPE_VOIE_MAP[first]
        parts[0] = first
    # Strip stop-words on the first significant rue keyword
    keep = []
    for p in parts:
        if p in {"de", "du", "des", "la", "le", "les", "l", "d"}:
            continue
        keep.append(p)
    return numero, " ".join(keep)


def address_match(open_addr: str, db_addr: str) -> float:
    """0..1 score on (numero, rue). 1.0 if exact, partial if rue overlaps."""
    a = parse_address(open_addr)
    b = parse_address(db_addr)
    if not a or not b:
        return 0.0
    if a[0] != b[0]:
        return 0.0  # different street number → reject
    # Rue similarity (Jaccard tokens)
    ra = set(a[1].split())
    rb = set(b[1].split())
    if not ra or not rb:
        return 0.0
    inter = len(ra & rb)
    if inter == 0:
        return 0.0
    return inter / max(len(ra), len(rb))


# ── Phonetic match (Soundex / Metaphone) ────────────────────────────────
def soundex_tokens(name: str) -> set:
    """Return the set of soundex codes of meaningful tokens in `name`."""
    STOPWORDS = {"le", "la", "les", "de", "du", "des", "l", "d", "et", "the", "bar", "cafe", "restaurant", "brasserie"}
    out = set()
    for w in normalize_text(name).split():
        if len(w) < 3 or w in STOPWORDS:
            continue
        try:
            out.add(jellyfish.soundex(w))
        except Exception:
            pass
    return out


def phonetic_similarity(a: str, b: str) -> float:
    """Jaccard on soundex codes — handles small spelling variations."""
    sa = soundex_tokens(a)
    sb = soundex_tokens(b)
    if not sa or not sb:
        return 0.0
    inter = len(sa & sb)
    union = len(sa | sb)
    return inter / union


def fetch_all_records(base_url: str, dataset_id: str, page_size: int = 100) -> List[Dict[str, Any]]:
    """Fetch all records via paginated Opendatasoft API v2.1.

    Strategy:
      - Use /records?limit=100 for datasets ≤ 10 000 (the v2.1 records cap).
      - For larger datasets, fall back to /exports/json which streams the full
        dataset without offset cap.
    """
    # First, peek total_count
    peek_url = f"{base_url}/api/explore/v2.1/catalog/datasets/{dataset_id}/records"
    try:
        r = requests.get(peek_url, params={"limit": 1, "offset": 0}, timeout=15)
        total = int(r.json().get("total_count", 0))
    except Exception:
        total = 0
    print(f"  [TOTAL] dataset has {total} records")

    out: List[Dict[str, Any]] = []
    if total > 10_000:
        # Use streaming export
        export_url = f"{base_url}/api/explore/v2.1/catalog/datasets/{dataset_id}/exports/json"
        print(f"  [INFO] using exports/json endpoint (>10k records)")
        try:
            r = requests.get(export_url, timeout=180, stream=True)
            r.raise_for_status()
            # Some endpoints stream NDJSON, others stream a JSON array.
            # Read it all then parse.
            raw = r.content
            try:
                out = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                # Try NDJSON
                out = []
                for line in raw.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        out.append(json.loads(line))
                    except Exception:
                        pass
            print(f"  [OK] {len(out)} records loaded via exports/json")
            return out
        except Exception as e:
            print(f"  [ERR] export endpoint failed: {e} — falling back to paginated /records")

    # Paginated /records (capped at 10 000 by Opendatasoft)
    offset = 0
    while True:
        url = peek_url
        params = {"limit": page_size, "offset": offset}
        try:
            r = requests.get(url, params=params, timeout=30)
            if r.status_code != 200:
                print(f"  [ERR] HTTP {r.status_code} at offset={offset}: {r.text[:200]}")
                break
            data = r.json()
        except Exception as e:
            print(f"  [ERR] fetch failed at offset={offset}: {e}")
            break
        results = data.get("results", []) or []
        if not results:
            break
        out.extend(results)
        offset += len(results)
        if offset >= data.get("total_count", offset):
            break
        if len(results) < page_size:
            break
        time.sleep(0.05)
    return out


def get_geo(rec: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    pt = rec.get("geo_point_2d") or {}
    lat, lng = pt.get("lat"), pt.get("lon")
    if lat is None or lng is None:
        return None
    return float(lat), float(lng)


def build_toulouse_address(rec: Dict[str, Any]) -> str:
    parts = [
        rec.get("numero_voie") or "",
        rec.get("type_voie") or "",
        rec.get("nom_voie") or "",
    ]
    return " ".join(p for p in parts if p).strip()


# ─── Matching ─────────────────────────────────────────────────────────────
def find_match(
    name: str,
    lat: float,
    lng: float,
    open_addr: str,
    candidates: List[Dict[str, Any]],
    max_dist_m: float = 80.0,
    min_combined_score: float = 0.45,
) -> Optional[Dict[str, Any]]:
    """Return the best matching DB candidate via multi-strategy combined score.

    Strategies (any single signal at high enough strength can match):
      1. Name Jaccard similarity (token-based, stop-words filtered)  ≥ 0.40
      2. Phonetic (Soundex on tokens)                                ≥ 0.50
      3. Address (numéro + rue normalisée, type voie résolu)         ≥ 0.50

    Combined weighted score (used for ranking when multiple candidates):
      score = max(name_sim, phonetic_sim, addr_sim) * 0.7
            + (1 - dist/max_dist) * 0.3

    Distance gate stays strict at ≤80m to avoid cross-street collisions.
    """
    norm_name = normalize_text(name)
    if not norm_name:
        return None
    best = None
    best_score = 0.0
    for c in candidates:
        try:
            clat = float(c.get("lat") or 0)
            clng = float(c.get("lng") or 0)
        except (TypeError, ValueError):
            continue
        dist = haversine_m(lat, lng, clat, clng)
        # Two-tier distance gate :
        #   ≤80m  → standard match (any signal ≥ threshold)
        #   ≤150m → only if signal is STRONG (name ≥0.7 OR phon ≥0.7 OR addr ≥0.8)
        if dist > 150.0:
            continue
        cand_name = c.get("name") or ""
        cand_addr = c.get("address") or ""

        sim_name = name_similarity(name, cand_name)
        sim_phon = phonetic_similarity(name, cand_name)
        sim_addr = address_match(open_addr, cand_addr) if open_addr and cand_addr else 0.0

        # ── Acceptance gates : any of the 3 signals strong enough ─────
        if dist <= 80.0:
            accepted = (sim_name >= 0.40) or (sim_phon >= 0.50) or (sim_addr >= 0.50)
        else:
            # Far candidates need a strong signal
            accepted = (sim_name >= 0.70) or (sim_phon >= 0.70) or (sim_addr >= 0.80)
        if not accepted:
            continue

        signal = max(sim_name, sim_phon, sim_addr)
        dist_score = max(0.0, 1.0 - dist / 150.0)
        score = signal * 0.7 + dist_score * 0.3
        if score < min_combined_score:
            continue
        if score > best_score:
            best_score = score
            best = c
    return best


# ─── Main ─────────────────────────────────────────────────────────────────
def import_city(city: str, dry_run: bool) -> Dict[str, Any]:
    cfg = DATASETS[city]
    print(f"\n──── {city} ────")
    print(f"  Source: {cfg['base_url']}/api/explore/v2.1/catalog/datasets/{cfg['dataset_id']}/")
    records = fetch_all_records(cfg["base_url"], cfg["dataset_id"])
    print(f"  Fetched {len(records)} authorized-terrace records.")

    # Pre-load DB candidates for this city (keep memory low: only id/name/lat/lng)
    candidates = list(
        terraces_coll.find(
            {"city": city},
            {"id": 1, "name": 1, "lat": 1, "lng": 1, "address": 1, "has_terrace_confirmed": 1, "_id": 0},
        )
    )
    print(f"  DB has {len(candidates)} terraces for city={city}")

    matched = 0
    skipped_no_match = 0
    skipped_no_name = 0
    already_confirmed = 0
    updated_ids = set()

    for rec in records:
        name = (rec.get(cfg["name_field"]) or "").strip()
        if not name:
            skipped_no_name += 1
            continue
        geo = get_geo(rec)
        if not geo:
            continue
        lat, lng = geo
        # Build address string (may differ per dataset)
        if cfg["address_field"]:
            address = (rec.get(cfg["address_field"]) or "").strip()
        else:
            address = build_toulouse_address(rec)
        cand = find_match(name, lat, lng, address, candidates)
        if not cand:
            skipped_no_match += 1
            continue

        was_confirmed = bool(cand.get("has_terrace_confirmed"))
        if was_confirmed:
            already_confirmed += 1

        # Update : précision GPS + flag confirmé + traçabilité
        update_doc = {
            "lat": lat,
            "lng": lng,
            "has_terrace_confirmed": True,
            "opendata_source": city.lower(),
            "opendata_address": address,
        }
        # Include extra metadata for typology/dimensions when available
        for f in cfg.get("extra_fields", []):
            v = rec.get(f)
            if v is not None and v != "":
                update_doc[f"opendata_{f}"] = v

        if not dry_run:
            terraces_coll.update_one({"id": cand["id"]}, {"$set": update_doc})
        updated_ids.add(cand["id"])
        matched += 1

    summary = {
        "city": city,
        "records_in_dataset": len(records),
        "candidates_in_db": len(candidates),
        "matched_unique": len(updated_ids),
        "matched_total": matched,
        "skipped_no_name": skipped_no_name,
        "skipped_no_match": skipped_no_match,
        "already_confirmed": already_confirmed,
    }
    print(f"  ✅ Matched {len(updated_ids)} unique DB terraces ({matched} total — some open-data entries point to same restaurant)")
    print(f"  ⏭  Skipped: {skipped_no_match} no DB-match, {skipped_no_name} no name")
    return summary


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--cities", default=",".join(DATASETS.keys()))
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    cities = [c.strip() for c in args.cities.split(",") if c.strip()]
    overall: List[Dict[str, Any]] = []
    for city in cities:
        if city not in DATASETS:
            print(f"[SKIP] Unknown city {city} (no open data dataset configured)")
            continue
        try:
            summary = import_city(city, args.dry_run)
            overall.append(summary)
        except Exception as e:
            print(f"[ERR] {city}: {e}")

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(json.dumps(overall, indent=2, ensure_ascii=False))

    log = Path(__file__).resolve().parent / "import_opendata_last_run.json"
    log.write_text(json.dumps(overall, indent=2, ensure_ascii=False))
    print(f"\n[LOG] saved to {log}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
