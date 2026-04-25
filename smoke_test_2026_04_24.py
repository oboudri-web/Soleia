"""
Smoke test complet backend Soleia — 2026-04-24
Valide tous les endpoints listés dans la review request après les changements:
 - /api/shadows MAX_SPAN 0.0601 → 0.0801
 - shadow_engine.project_shadow_polygons_latlng max_polys 120 → 300

Base URL: REACT_APP_BACKEND_URL (prod preview). Les endpoints /api/auth/* sont ignorés
(Google Sign-In retiré du projet).

Usage: python3 /app/smoke_test_2026_04_24.py
"""
from __future__ import annotations
import base64
import json
import os
import sys
import time
import traceback
import uuid
from typing import Any

import requests
from pymongo import MongoClient

# Read frontend .env to get REACT_APP_BACKEND_URL / EXPO_PUBLIC_BACKEND_URL
FRONTEND_ENV = "/app/frontend/.env"
BASE_URL = None
with open(FRONTEND_ENV, "r") as f:
    for line in f:
        line = line.strip()
        if line.startswith("EXPO_PUBLIC_BACKEND_URL="):
            BASE_URL = line.split("=", 1)[1].strip().strip('"').strip("'")
        elif line.startswith("REACT_APP_BACKEND_URL=") and not BASE_URL:
            BASE_URL = line.split("=", 1)[1].strip().strip('"').strip("'")
if not BASE_URL:
    raise SystemExit("Cannot find EXPO_PUBLIC_BACKEND_URL/REACT_APP_BACKEND_URL in /app/frontend/.env")

API = BASE_URL.rstrip("/") + "/api"
print(f"[smoke] API base = {API}")

# Mongo direct pour cleanup
MONGO_URL = None
with open("/app/backend/.env", "r") as f:
    for line in f:
        if line.startswith("MONGO_URL="):
            MONGO_URL = line.split("=", 1)[1].strip().strip('"').strip("'")
DB_NAME = None
with open("/app/backend/.env", "r") as f:
    for line in f:
        if line.startswith("DB_NAME="):
            DB_NAME = line.split("=", 1)[1].strip().strip('"').strip("'")
mongo = MongoClient(MONGO_URL)
mdb = mongo[DB_NAME or "test_database"]

RESULTS: list[tuple[str, bool, str]] = []


def check(label: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((label, ok, detail))
    prefix = "✅" if ok else "❌"
    print(f"{prefix} {label}  {detail}")
    return ok


def get(path: str, params: dict | None = None, timeout: int = 30) -> tuple[int, Any]:
    try:
        r = requests.get(API + path, params=params, timeout=timeout)
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, r.text
    except Exception as e:
        return 0, f"EXC:{e}"


def post(path: str, body: dict | None = None, params: dict | None = None, timeout: int = 30) -> tuple[int, Any]:
    try:
        r = requests.post(API + path, json=body, params=params, timeout=timeout)
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, r.text
    except Exception as e:
        return 0, f"EXC:{e}"


# 1 — P0 core endpoints ------------------------------------------------------
print("\n── P0 core endpoints ──")

code, body = get("/cities")
ok = code == 200 and isinstance(body, list) and "Nantes" in body
check("cities.list", ok, f"status={code} cities={body if ok else str(body)[:120]}")

code, body = get("/terraces", {"city": "Nantes", "limit": 100})
count = body.get("count") if isinstance(body, dict) else None
ok = code == 200 and count is not None and count > 0 and all("sun_status" in t for t in body.get("terraces", []))
leak_shadow = any("shadow_map" in t for t in body.get("terraces", [])) if isinstance(body, dict) else False
leak_photos = any("community_photos" in t for t in body.get("terraces", [])) if isinstance(body, dict) else False
check("terraces.city=Nantes.limit=100", ok and not leak_shadow and not leak_photos,
      f"status={code} count={count} leak_shadow={leak_shadow} leak_photos={leak_photos}")

# bbox + at_time
code, body = get("/terraces", {
    "city": "Nantes",
    "lat_min": 47.20, "lat_max": 47.25,
    "lng_min": -1.58, "lng_max": -1.53,
    "at_time": "2026-04-24T15:00:00",
})
count = body.get("count") if isinstance(body, dict) else None
bbox = body.get("query", {}).get("bbox") if isinstance(body, dict) else None
ok = code == 200 and count is not None and bbox == [47.20, -1.58, 47.25, -1.53]
# All terraces within bbox
all_in = True
if isinstance(body, dict):
    for t in body.get("terraces", []):
        if not (47.20 <= t.get("lat", 0) <= 47.25 and -1.58 <= t.get("lng", 0) <= -1.53):
            all_in = False
            break
check("terraces.bbox+at_time", ok and all_in, f"status={code} count={count} bbox={bbox} all_in={all_in}")

# Get a detail - use Le Lieu Unique
LIEU_UNIQUE_ID = "57c290ff-05bc-402f-afca-d9e939322808"
code, body = get(f"/terraces/{LIEU_UNIQUE_ID}")
has_schedule = isinstance(body, dict) and isinstance(body.get("sun_schedule_today"), dict)
has_hourly = isinstance(body, dict) and isinstance(body.get("hourly_forecast"), list)
leak = isinstance(body, dict) and ("shadow_map" in body or "community_photos" in body)
check("terraces.detail.LieuUnique", code == 200 and has_schedule and has_hourly and not leak,
      f"status={code} schedule={has_schedule} hourly={has_hourly} leak={leak}")

# 404
code, body = get("/terraces/nonexistent-xyz-123")
check("terraces.detail.404", code == 404, f"status={code}")

# weather
code, body = get("/weather/Nantes")
if code == 502:
    check("weather.Nantes(accept502)", True, f"status=502 (Open-Meteo rate-limit, non-bloquant)")
else:
    ok = code == 200 and isinstance(body, dict) and "temperature" in body
    check("weather.Nantes", ok, f"status={code} keys={list(body.keys()) if isinstance(body, dict) else str(body)[:100]}")

code, body = get("/weather/Atlantis")
check("weather.Atlantis.404", code == 404, f"status={code}")

# 2 — /api/shadows tests ------------------------------------------------------
print("\n── /api/shadows (P0 focus) ──")

# Small bbox (span 0.03) — should return polys (up to 300)
params = {"lat_min": 47.21, "lat_max": 47.24, "lng_min": -1.57, "lng_max": -1.54, "at_time": "2026-04-24T14:00:00"}
t0 = time.time()
code, body = get("/shadows", params, timeout=60)
dt = time.time() - t0
polys = body.get("polygons") if isinstance(body, dict) else None
sun = body.get("sun") if isinstance(body, dict) else None
bc = body.get("building_count") if isinstance(body, dict) else None
cached = body.get("cached") if isinstance(body, dict) else None
ok = code == 200 and isinstance(polys, list) and isinstance(sun, dict) and sun.get("el") is not None
check("shadows.small_bbox_0.03", ok,
      f"status={code} polys={len(polys) if polys else 'None'} bc={bc} sun_el={sun.get('el') if sun else None} cached={cached} dt={dt:.2f}s")

# polys up to 300 max (max_polys change)
if isinstance(polys, list):
    polys_count = len(polys)
    check("shadows.small_bbox.polys_within_300", polys_count <= 300,
          f"polys={polys_count} (<=300 expected)")

# Medium bbox span ~0.08 — should NOT be rejected (MAX_SPAN change from 0.0601 to 0.0801)
params = {"lat_min": 47.19, "lat_max": 47.27, "lng_min": -1.60, "lng_max": -1.52, "at_time": "2026-04-24T14:00:00"}
t0 = time.time()
code, body = get("/shadows", params, timeout=90)
dt = time.time() - t0
reason = body.get("reason") if isinstance(body, dict) else None
polys = body.get("polygons") if isinstance(body, dict) else None
ok = code == 200 and reason != "bbox_invalid_or_too_large" and isinstance(polys, list)
check("shadows.bbox_0.08_not_rejected", ok,
      f"status={code} reason={reason} polys={len(polys) if polys else 'None'} dt={dt:.2f}s")
if isinstance(polys, list):
    check("shadows.bbox_0.08.polys_cap_300", len(polys) <= 300, f"polys={len(polys)}")

# Too large bbox span 0.1 — must be rejected
params = {"lat_min": 47.19, "lat_max": 47.29, "lng_min": -1.60, "lng_max": -1.50, "at_time": "2026-04-24T14:00:00"}
code, body = get("/shadows", params, timeout=30)
reason = body.get("reason") if isinstance(body, dict) else None
ok = code == 200 and reason == "bbox_invalid_or_too_large" and body.get("polygons") == []
check("shadows.bbox_0.10_rejected", ok, f"status={code} reason={reason}")

# Cache behavior: 2nd call immediate
params = {"lat_min": 47.21, "lat_max": 47.24, "lng_min": -1.57, "lng_max": -1.54, "at_time": "2026-04-24T14:00:00"}
t0 = time.time()
code, body = get("/shadows", params, timeout=30)
dt2 = time.time() - t0
cached2 = body.get("cached") if isinstance(body, dict) else None
check("shadows.cache_hit", code == 200 and cached2 is True and dt2 < 2.0,
      f"status={code} cached={cached2} dt={dt2:.3f}s")

# Night: sun el<0 or polys=[]
code, body = get("/shadows", {"lat_min": 47.21, "lat_max": 47.24, "lng_min": -1.57, "lng_max": -1.54, "at_time": "2026-04-24T23:00:00"}, timeout=60)
sun = body.get("sun") if isinstance(body, dict) else {}
polys = body.get("polygons") if isinstance(body, dict) else None
ok = code == 200 and (sun.get("el") is None or sun.get("el") <= 2 or (isinstance(polys, list) and len(polys) == 0))
check("shadows.night", ok, f"status={code} sun_el={sun.get('el')} polys={len(polys) if polys else 'None'}")

# Bbox inversé (lat_max < lat_min)
code, body = get("/shadows", {"lat_min": 47.24, "lat_max": 47.21, "lng_min": -1.57, "lng_max": -1.54}, timeout=30)
reason = body.get("reason") if isinstance(body, dict) else None
check("shadows.bbox_inverted", code == 200 and reason == "bbox_invalid_or_too_large", f"status={code} reason={reason}")

# 3 — Crowdsourcing (P1) -----------------------------------------------------
print("\n── Crowdsourcing (P1) ──")

# Create temp terrace via submit
marker = uuid.uuid4().hex[:8]
submit_body = {
    "name": f"SmokeTestBar_{marker}",
    "type": "bar",
    "orientation_label": "sud",
    "lat": 47.2184,
    "lng": -1.5536,
    "city": "Nantes",
    "user_id": "smoke_test",
}
code, body = post("/terraces/submit", submit_body)
new_id = body.get("id") if isinstance(body, dict) else None
doc = mdb.terraces.find_one({"id": new_id}) if new_id else None
ok = code == 200 and new_id and doc and doc.get("orientation_degrees") == 180 and doc.get("status") == "pending_review" and doc.get("terrace_source") == "user_submission"
check("submit.orientation_label=sud", ok, f"status={code} id={new_id} ori={doc.get('orientation_degrees') if doc else None}")

# Also test orientation_degrees direct
submit2 = {
    "name": f"SmokeTestBar2_{marker}",
    "type": "cafe",
    "orientation_degrees": 135,
    "lat": 47.2184,
    "lng": -1.5536,
    "city": "Nantes",
}
code, body = post("/terraces/submit", submit2)
new_id2 = body.get("id") if isinstance(body, dict) else None
doc2 = mdb.terraces.find_one({"id": new_id2}) if new_id2 else None
ok = code == 200 and new_id2 and doc2 and abs(doc2.get("orientation_degrees", 0) - 135) < 0.1
check("submit.orientation_degrees=135", ok, f"status={code} ori={doc2.get('orientation_degrees') if doc2 else None}")

# Validation: missing name
code, _ = post("/terraces/submit", {"city": "Nantes", "lat": 47.2, "lng": -1.5})
check("submit.missing_name.400", code == 400, f"status={code}")

# Reports: confirmed/wrong_orientation/no_terrace
if new_id:
    code, body = post(f"/terraces/{new_id}/report", {"type": "confirmed", "user_id": "u1"})
    ok = code == 200 and body.get("ok") and body.get("reports", {}).get("confirmed") == 1
    check("report.confirmed", ok, f"status={code} body={body if ok else str(body)[:100]}")

    code, body = post(f"/terraces/{new_id}/report", {"type": "wrong_orientation"})
    check("report.wrong_orientation", code == 200 and body.get("ok"), f"status={code}")

    # 3x no_terrace → hidden
    for i in range(3):
        code, body = post(f"/terraces/{new_id}/report", {"type": "no_terrace", "user_id": f"u{i+10}"})
    hidden = body.get("hidden") if isinstance(body, dict) else None
    check("report.no_terrace.auto_mask", code == 200 and hidden is True,
          f"status={code} hidden={hidden} reports={body.get('reports') if isinstance(body, dict) else None}")

    # Invalid type
    code, _ = post(f"/terraces/{new_id}/report", {"type": "invalid_type"})
    check("report.invalid_type.400", code == 400, f"status={code}")

# Report on nonexistent
code, _ = post("/terraces/nonexistent-xyz/report", {"type": "confirmed"})
check("report.nonexistent.404", code == 404, f"status={code}")

# Photo — base64 PNG 1px
png_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
if new_id2:
    code, body = post(f"/terraces/{new_id2}/photo", {"image_base64": png_b64, "user_id": "smoke", "caption": "smoke test"})
    pid = body.get("photo_id") if isinstance(body, dict) else None
    ok = code == 200 and pid
    check("photo.valid_png", ok, f"status={code} photo_id={pid}")

    # Empty base64
    code, _ = post(f"/terraces/{new_id2}/photo", {"image_base64": ""})
    check("photo.empty.400", code == 400, f"status={code}")

    # Too large
    big = "A" * 4_000_000
    code, _ = post(f"/terraces/{new_id2}/photo", {"image_base64": big})
    check("photo.too_large.413", code == 413, f"status={code}")

# Photo on nonexistent
code, _ = post("/terraces/nonexistent-xyz/photo", {"image_base64": png_b64})
check("photo.nonexistent.404", code == 404, f"status={code}")

# Search
code, body = get("/terraces/search", {"q": "lieu", "city": "Nantes"})
results = body.get("results") if isinstance(body, dict) else []
first = results[0].get("name") if results else None
ok = code == 200 and first == "Le Lieu Unique"
# 0 leak
leak = any("shadow_map" in r or "community_photos" in r for r in results) if results else False
check("search.q=lieu&city=Nantes.top1=LieuUnique", ok and not leak,
      f"status={code} top={first} leak={leak} count={len(results)}")

code, body = get("/terraces/search", {"q": "xyznothing_smoke"})
check("search.no_results", code == 200 and body.get("count") == 0, f"status={code} count={body.get('count') if isinstance(body, dict) else None}")

# 4 — Pro portal (P1) -------------------------------------------------------
print("\n── Pro portal (P1) ──")

pro_email = f"smoke.pro.{marker}@example.fr"
code, body = post("/pro/contact", {
    "establishment_name": f"SmokeTest Pro {marker}",
    "email": pro_email,
    "city": "Nantes",
    "message": "Smoke test — please delete.",
})
pro_id = body.get("id") if isinstance(body, dict) else None
check("pro.contact.valid", code == 200 and pro_id, f"status={code} id={pro_id}")

# Invalid email
code, _ = post("/pro/contact", {"establishment_name": "X", "email": "notanemail", "city": "Nantes"})
check("pro.contact.invalid_email.400", code == 400, f"status={code}")

# Empty name
code, _ = post("/pro/contact", {"establishment_name": "", "email": "a@b.fr", "city": "Nantes"})
check("pro.contact.empty_name.400", code == 400, f"status={code}")

# GET /pro/leads contains our new lead
code, body = get("/pro/leads")
leads = body.get("leads") if isinstance(body, dict) else []
found = any(l.get("email") == pro_email for l in leads) if leads else False
check("pro.leads.contains_new", code == 200 and found,
      f"status={code} nb_leads={len(leads)} found={found}")

# 5 — Derived endpoints (P2) -------------------------------------------------
print("\n── Derived endpoints (P2) ──")

# next-sunny
code, body = get("/next-sunny", {"city": "Nantes"})
ok = code == 200 and isinstance(body, dict) and "found" in body
check("next-sunny.Nantes", ok, f"status={code} found={body.get('found') if isinstance(body, dict) else None}")

# sun-position
code, body = get("/sun-position", {"lat": 47.2184, "lng": -1.5536})
ok = code == 200 and isinstance(body, dict) and body.get("position", {}).get("azimuth") is not None
check("sun-position", ok, f"status={code}")

# sun-check
code, body = post("/sun-check", {"lat": 47.2184, "lng": -1.5536, "orientation_degrees": 180})
check("sun-check.valid", code == 200 and "is_sunny" in body, f"status={code}")
code, body = post("/sun-check", {"lat": 47.2184, "lng": -1.5536})
check("sun-check.missing_field.400", code == 400, f"status={code}")

# favorites batch resolution
code, body = post("/terraces/favorites", {"ids": [LIEU_UNIQUE_ID, "nonexistent-zzz"]})
count = body.get("count") if isinstance(body, dict) else None
ok = code == 200 and count == 1 and body.get("terraces", [{}])[0].get("id") == LIEU_UNIQUE_ID
check("favorites.batch", ok, f"status={code} count={count}")

# notifications register (idempotent)
tok = f"ExponentPushToken[smoke-{marker}]"
code, body = post("/notifications/register", {"push_token": tok, "city": "Nantes"})
ok = code == 200 and body.get("ok") and body.get("updated") is False
check("notifications.register.first", ok, f"status={code} body={body if isinstance(body, dict) else str(body)[:80]}")
code, body = post("/notifications/register", {"push_token": tok, "city": "Nantes"})
ok = code == 200 and body.get("updated") is True
check("notifications.register.idempotent", ok, f"status={code} updated={body.get('updated') if isinstance(body, dict) else None}")

# generate-description (Claude)
code, body = post(f"/terraces/{LIEU_UNIQUE_ID}/generate-description", {})
ok = code == 200 and isinstance(body, dict) and isinstance(body.get("description"), str) and len(body.get("description", "")) > 20
check("generate-description", ok, f"status={code} len={len(body.get('description', '')) if isinstance(body, dict) else 0}")

# root
code, body = get("/")
check("root", code == 200, f"status={code}")

# 6 — Cleanup ----------------------------------------------------------------
print("\n── Cleanup ──")

del_terraces = mdb.terraces.delete_many({"name": {"$regex": f"SmokeTest.*{marker}"}})
del_reports = mdb.reports.delete_many({"terrace_id": {"$in": [new_id, new_id2] if new_id and new_id2 else []}})
del_pro = mdb.pro_leads.delete_many({"email": pro_email})
del_tok = mdb.push_tokens.delete_many({"token": {"$regex": f"smoke-{marker}"}})
# Remove any community_photos smoke entries from Le Lieu Unique
mdb.terraces.update_one(
    {"id": LIEU_UNIQUE_ID},
    {"$pull": {"community_photos": {"caption": "smoke test"}}},
)
print(f"[cleanup] terraces={del_terraces.deleted_count} reports={del_reports.deleted_count} pro_leads={del_pro.deleted_count} push_tokens={del_tok.deleted_count}")

# Summary --------------------------------------------------------------------
print("\n" + "=" * 70)
pass_count = sum(1 for _, ok, _ in RESULTS if ok)
fail_count = sum(1 for _, ok, _ in RESULTS if not ok)
print(f"TOTAL: {pass_count}/{len(RESULTS)} PASS, {fail_count} FAIL")
if fail_count:
    print("\nFAILURES:")
    for label, ok, detail in RESULTS:
        if not ok:
            print(f"  ❌ {label}  {detail}")
sys.exit(0 if fail_count == 0 else 1)
