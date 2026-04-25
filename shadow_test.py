"""
Shadow engine 3D integration test (Nantes pilot).
Tests:
  1. shadow_analyzed coverage on Nantes
  2. Non-regression on other cities
  3. Detail endpoint consistency (Le Lieu Unique)
  4. Search endpoint carries shadow flags
  5. at_time lookup works
  6. Non-regression on core endpoints
  7. Robustness (404 + concurrency)
"""
import os
import sys
import json
import time
import base64
import asyncio
import concurrent.futures
import requests
from pathlib import Path
from dotenv import load_dotenv

FRONTEND_ENV = Path(__file__).parent / "frontend" / ".env"
load_dotenv(FRONTEND_ENV)
BASE = os.environ.get("EXPO_PUBLIC_BACKEND_URL") or os.environ.get("REACT_APP_BACKEND_URL")
if not BASE:
    print("FATAL: backend URL not set")
    sys.exit(1)
BASE = BASE.rstrip("/") + "/api"

LE_LIEU_UNIQUE_ID = "57c290ff-05bc-402f-afca-d9e939322808"

PASS = []
FAIL = []


def record(name: str, ok: bool, detail: str = "") -> None:
    bucket = PASS if ok else FAIL
    bucket.append((name, detail))
    tag = "PASS" if ok else "FAIL"
    print(f"[{tag}] {name}" + (f"  — {detail}" if detail else ""))


def extract(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        return payload.get("terraces") or payload.get("results") or []
    return []


# =========================================================
# 1. Nantes coverage
# =========================================================
print("\n===== 1. NANTES SHADOW COVERAGE =====")
r = requests.get(f"{BASE}/terraces", params={"city": "Nantes"}, timeout=30)
record("GET /terraces?city=Nantes returns 200", r.status_code == 200, f"status={r.status_code}")

nantes = extract(r.json()) if r.status_code == 200 else []
record("Nantes has 21 terraces", len(nantes) == 21, f"got {len(nantes)}")

n_analyzed = sum(1 for t in nantes if t.get("shadow_analyzed") is True)
record("All 21 Nantes terraces have shadow_analyzed=true", n_analyzed == 21, f"analyzed {n_analyzed}/{len(nantes)}")

# shadow_map must NOT be in public payload
leaked = [t.get("id") for t in nantes if "shadow_map" in t]
record("shadow_map is stripped from /terraces response (Nantes)", not leaked, f"leaked ids={leaked[:3]}")

overridden = [t for t in nantes if t.get("shadow_override") is True]
record("At least one Nantes terrace has shadow_override=true",
       len(overridden) >= 1, f"count={len(overridden)}")

# We need shadow_buildings_count and shadow_sunny_minutes exposed
with_bc = [t for t in nantes if isinstance(t.get("shadow_buildings_count"), int) and t["shadow_buildings_count"] > 0]
record("shadow_buildings_count > 0 on every Nantes terrace",
       len(with_bc) == len(nantes), f"{len(with_bc)}/{len(nantes)}")

with_min = [t for t in nantes if isinstance(t.get("shadow_sunny_minutes"), int) and 0 <= t["shadow_sunny_minutes"] <= 960]
record("shadow_sunny_minutes between 0 and 960 on every Nantes terrace",
       len(with_min) == len(nantes), f"{len(with_min)}/{len(nantes)}")


# =========================================================
# 2. Non-regression on other cities
# =========================================================
print("\n===== 2. NON-REGRESSION ON OTHER CITIES =====")
for city in ("Paris", "Lyon"):
    r = requests.get(f"{BASE}/terraces", params={"city": city}, timeout=30)
    ok = r.status_code == 200
    record(f"GET /terraces?city={city} returns 200", ok, f"status={r.status_code}")
    if not ok:
        continue
    arr = extract(r.json())
    record(f"{city} has terraces (>0)", len(arr) > 0, f"count={len(arr)}")

    # Those must NOT be analyzed (or absent / falsy)
    analyzed = [t for t in arr if t.get("shadow_analyzed") is True]
    record(f"{city}: shadow_analyzed is false/absent for all", len(analyzed) == 0,
           f"leaked analyzed={len(analyzed)}/{len(arr)}")

    # Must still have sun_status
    missing_status = [t for t in arr if not t.get("sun_status")]
    record(f"{city}: sun_status present on all terraces",
           not missing_status, f"missing={len(missing_status)}")

    leaked_map = [t for t in arr if "shadow_map" in t]
    record(f"{city}: shadow_map not leaked", not leaked_map, f"leaked={len(leaked_map)}")


# =========================================================
# 3. Detail endpoint (Le Lieu Unique)
# =========================================================
print("\n===== 3. DETAIL ENDPOINT — Le Lieu Unique =====")
r = requests.get(f"{BASE}/terraces/{LE_LIEU_UNIQUE_ID}", timeout=30)
record("GET /terraces/<lieuUniqueId> returns 200", r.status_code == 200, f"status={r.status_code}")
if r.status_code == 200:
    d = r.json()
    record("Detail: shadow_analyzed == true",
           d.get("shadow_analyzed") is True, f"val={d.get('shadow_analyzed')}")
    sb = d.get("shadow_buildings_count")
    record("Detail: shadow_buildings_count >= 50",
           isinstance(sb, int) and sb >= 50, f"val={sb}")
    sm = d.get("shadow_sunny_minutes")
    record("Detail: shadow_sunny_minutes >= 60",
           isinstance(sm, int) and sm >= 60, f"val={sm}")
    # sun_status coherent with is_sunny
    ss, isun = d.get("sun_status"), d.get("is_sunny")
    coherent = (ss == "sunny" and isun is True) or (ss in ("shade", "soon") and isun is False)
    record("Detail: sun_status coherent with is_sunny",
           coherent, f"sun_status={ss} is_sunny={isun}")
    record("Detail: sun_schedule_today present",
           isinstance(d.get("sun_schedule_today"), dict), f"{type(d.get('sun_schedule_today')).__name__}")
    record("Detail: hourly_forecast present",
           isinstance(d.get("hourly_forecast"), list) and len(d["hourly_forecast"]) > 0,
           f"len={len(d.get('hourly_forecast', []))}")
    record("Detail: shadow_map NOT present in response (stripped)",
           "shadow_map" not in d, f"keys contain shadow_map")


# =========================================================
# 4. Search endpoint
# =========================================================
print("\n===== 4. SEARCH ENDPOINT =====")
r = requests.get(f"{BASE}/terraces/search", params={"q": "lieu", "city": "Nantes"}, timeout=30)
record("GET /terraces/search?q=lieu&city=Nantes returns 200", r.status_code == 200, f"status={r.status_code}")
if r.status_code == 200:
    res = r.json().get("results", [])
    record("Search: at least 1 result", len(res) > 0, f"count={len(res)}")
    analyzed_all = all(t.get("shadow_analyzed") is True for t in res)
    record("Search: all results have shadow_analyzed=true",
           analyzed_all, f"results_count={len(res)}")
    leak = [t for t in res if "shadow_map" in t]
    record("Search: shadow_map not leaked", not leak, f"leaked={len(leak)}")


# =========================================================
# 5. Temporal override (at_time)
# =========================================================
print("\n===== 5. AT_TIME LOOKUP =====")
# Pick a terrace with shadow_override true, or fallback to Le Lieu Unique
target_id = (overridden[0]["id"] if overridden else LE_LIEU_UNIQUE_ID)
r10 = requests.get(f"{BASE}/terraces/{target_id}", params={"at_time": "10:00"}, timeout=30)
r14 = requests.get(f"{BASE}/terraces/{target_id}", params={"at_time": "14:00"}, timeout=30)
r18 = requests.get(f"{BASE}/terraces/{target_id}", params={"at_time": "18:00"}, timeout=30)
record("at_time=10:00 -> 200", r10.status_code == 200, f"status={r10.status_code}")
record("at_time=14:00 -> 200", r14.status_code == 200, f"status={r14.status_code}")
record("at_time=18:00 -> 200", r18.status_code == 200, f"status={r18.status_code}")
if r10.ok and r14.ok:
    j10, j14 = r10.json(), r14.json()
    print(f"    [info] {target_id} 10h sun_status={j10.get('sun_status')} is_sunny={j10.get('is_sunny')} | 14h sun_status={j14.get('sun_status')} is_sunny={j14.get('is_sunny')}")


# =========================================================
# 6. Non-regression core endpoints
# =========================================================
print("\n===== 6. NON-REGRESSION CORE =====")
r = requests.get(f"{BASE}/cities", timeout=30)
record("/cities returns 200", r.status_code == 200, f"status={r.status_code}")
if r.status_code == 200:
    cities = r.json()
    names = [c["name"] for c in cities]
    print(f"    [info] cities returned: {names}")
    required = {"Paris", "Lyon", "Marseille", "Bordeaux", "Nantes"}
    missing = required - set(names)
    record("/cities contains Paris, Lyon, Marseille, Bordeaux, Nantes",
           not missing, f"missing={missing}")
    expected_set = {"Paris", "Lyon", "Marseille", "Bordeaux", "Nantes"}
    record("/cities returns exactly 5 cities (spec says Paris/Lyon/Marseille/Bordeaux/Nantes)",
           set(names) == expected_set, f"got={sorted(names)} expected={sorted(expected_set)}")

# /next-sunny?city=Nantes
r = requests.get(f"{BASE}/next-sunny", params={"city": "Nantes"}, timeout=60)
record("/next-sunny?city=Nantes returns 200", r.status_code == 200, f"status={r.status_code}")
if r.status_code == 200:
    j = r.json()
    record("/next-sunny: found + terrace_id present",
           j.get("found") is True and j.get("terrace_id"), json.dumps(j)[:200])

# /sun-position
r = requests.get(f"{BASE}/sun-position", params={"lat": 47.2, "lng": -1.55}, timeout=30)
record("/sun-position returns 200", r.status_code == 200, f"status={r.status_code}")

# /sun-check
r = requests.post(f"{BASE}/sun-check", json={"lat": 47.2, "lng": -1.55, "orientation_degrees": 180}, timeout=30)
record("/sun-check returns 200", r.status_code == 200, f"status={r.status_code}")

# Weather (502 transient accepted)
r = requests.get(f"{BASE}/weather/Nantes", timeout=30)
ok = r.status_code in (200, 502)
record("/weather/Nantes returns 200 or 502 (transient)", ok, f"status={r.status_code}")

# Crowdsourcing quick smoke
r = requests.post(f"{BASE}/terraces/{LE_LIEU_UNIQUE_ID}/report", json={"type": "confirmed"}, timeout=30)
record("POST /report confirmed returns 200", r.status_code == 200, f"status={r.status_code}")

png_b64 = base64.b64encode(
    bytes.fromhex("89504E470D0A1A0A0000000D49484452000000010000000108060000001F15C4890000000D49444154789C6300010000000500010D0A2DB40000000049454E44AE426082")
).decode()
r = requests.post(f"{BASE}/terraces/{LE_LIEU_UNIQUE_ID}/photo",
                  json={"image_base64": png_b64, "caption": "smoke"}, timeout=30)
record("POST /photo returns 200", r.status_code == 200, f"status={r.status_code}")

lead = {"establishment_name": "Bar du Test Shadow", "email": "shadowtest@soleia.fr",
        "city": "Nantes", "message": "test"}
r = requests.post(f"{BASE}/pro/contact", json=lead, timeout=30)
record("POST /pro/contact returns 200", r.status_code == 200, f"status={r.status_code}")

submit = {"name": "Bar Shadow Smoke XYZ", "type": "bar", "orientation_label": "sud",
          "lat": 47.2, "lng": -1.55, "city": "Nantes"}
r = requests.post(f"{BASE}/terraces/submit", json=submit, timeout=30)
record("POST /terraces/submit returns 200", r.status_code == 200, f"status={r.status_code}")
submitted_id = r.json().get("id") if r.status_code == 200 else None


# =========================================================
# 7. Robustness
# =========================================================
print("\n===== 7. ROBUSTNESS =====")
r = requests.get(f"{BASE}/terraces/nonexistent-id", timeout=30)
record("/terraces/nonexistent-id -> 404", r.status_code == 404, f"status={r.status_code}")


def fetch_once(_):
    try:
        resp = requests.get(f"{BASE}/terraces", params={"city": "Nantes"}, timeout=30)
        return resp.status_code
    except Exception as exc:
        return f"ERR:{exc}"

with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
    codes = list(pool.map(fetch_once, range(20)))
all200 = all(c == 200 for c in codes)
record("20 concurrent /terraces?city=Nantes all return 200",
       all200, f"codes={set(codes)}")


# =========================================================
# CLEANUP
# =========================================================
print("\n===== CLEANUP =====")
try:
    from pymongo import MongoClient
    backend_env = Path(__file__).parent / "backend" / ".env"
    load_dotenv(backend_env)
    mongo = MongoClient(os.environ["MONGO_URL"])
    dbh = mongo[os.environ["DB_NAME"]]
    dbh.reports.delete_many({"terrace_id": LE_LIEU_UNIQUE_ID})
    dbh.terraces.update_one({"id": LE_LIEU_UNIQUE_ID},
                            {"$pull": {"community_photos": {"caption": "smoke"}},
                             "$unset": {"reports": "", "reports_updated_at": ""}})
    dbh.pro_leads.delete_many({"email": "shadowtest@soleia.fr"})
    if submitted_id:
        dbh.terraces.delete_one({"id": submitted_id})
    print("    [info] cleanup OK")
except Exception as e:
    print(f"    [warn] cleanup failed: {e}")


# =========================================================
print("\n====================== REPORT ======================")
print(f"PASSED: {len(PASS)}")
print(f"FAILED: {len(FAIL)}")
for name, detail in FAIL:
    print(f"  - {name}: {detail}")
print("====================================================")
sys.exit(0 if not FAIL else 1)
