#!/usr/bin/env python3
"""Non-regression test for Places Details enrichment (825 terrasses)."""
import os
import requests
import json
import base64
import sys

BASE = os.environ.get("BACKEND_URL", "https://sunny-terraces.preview.emergentagent.com") + "/api"

PASS = []
FAIL = []


def check(label, cond, detail=""):
    if cond:
        PASS.append(label)
        print(f"PASS  {label}  {detail}")
    else:
        FAIL.append((label, detail))
        print(f"FAIL  {label}  {detail}")


def t1_cities():
    r = requests.get(f"{BASE}/cities", timeout=15)
    check("T1 /cities 200", r.status_code == 200, f"status={r.status_code}")
    if r.status_code != 200:
        return
    data = r.json()
    names = [c["name"] for c in data]
    check("T1 /cities = 8 villes", len(data) == 8, f"count={len(data)} names={names}")
    expected = {"Paris", "Lyon", "Marseille", "Bordeaux", "Nantes", "Toulouse", "Nice", "Montpellier"}
    check("T1 /cities contient exactement les 8 attendues", set(names) == expected, f"missing={expected-set(names)} extra={set(names)-expected}")


def t2_la_cigale():
    tid = "81e95a94-271c-4242-bde1-6f764343335a"
    r = requests.get(f"{BASE}/terraces/{tid}", timeout=15)
    check("T2 /terraces/La Cigale 200", r.status_code == 200, f"status={r.status_code}")
    if r.status_code != 200:
        return
    d = r.json()
    check("T2 phone_number", d.get("phone_number") == "+33 2 51 84 94 94", f"got={d.get('phone_number')}")
    check("T2 website_uri", d.get("website_uri") == "http://www.lacigale.com/", f"got={d.get('website_uri')}")
    check("T2 price_level=2", d.get("price_level") == 2, f"got={d.get('price_level')}")
    oh = d.get("opening_hours") or {}
    wd = oh.get("weekday_descriptions")
    check(
        "T2 opening_hours.weekday_descriptions [7 strings]",
        isinstance(wd, list) and len(wd) == 7 and all(isinstance(x, str) for x in wd),
        f"type={type(wd).__name__} len={len(wd) if isinstance(wd, list) else 'n/a'}",
    )
    check("T2 details_enriched_at présent", bool(d.get("details_enriched_at")), f"got={d.get('details_enriched_at')}")
    # Regression checks
    check("T2 sun_status présent", d.get("sun_status") in ("sunny", "soon", "shade"), f"got={d.get('sun_status')}")
    check("T2 shadow_analyzed=true", d.get("shadow_analyzed") is True, f"got={d.get('shadow_analyzed')}")
    check("T2 hourly_forecast list>0", isinstance(d.get("hourly_forecast"), list) and len(d["hourly_forecast"]) > 0, f"len={len(d.get('hourly_forecast') or [])}")
    check("T2 sun_schedule_today présent", isinstance(d.get("sun_schedule_today"), dict), f"type={type(d.get('sun_schedule_today')).__name__}")
    # Leaks
    check("T2 PAS de shadow_map", "shadow_map" not in d, "leak!")
    check("T2 PAS de community_photos", "community_photos" not in d, "leak!")
    check("T2 reservable défini", "reservable" in d, f"present={'reservable' in d} val={d.get('reservable')}")


def t3_terraces_nantes():
    r = requests.get(f"{BASE}/terraces?city=Nantes", timeout=20)
    check("T3 /terraces?city=Nantes 200", r.status_code == 200)
    if r.status_code != 200:
        return
    body = r.json()
    data = body.get("terraces", body) if isinstance(body, dict) else body
    check("T3 Nantes count=21", len(data) == 21, f"count={len(data)}")
    # No leaks
    leaks_shadow = [t["id"] for t in data if "shadow_map" in t]
    leaks_cp = [t["id"] for t in data if "community_photos" in t]
    check("T3 0 shadow_map leak", len(leaks_shadow) == 0, f"leaks={leaks_shadow[:3]}")
    check("T3 0 community_photos leak", len(leaks_cp) == 0, f"leaks={leaks_cp[:3]}")
    # Enriched count
    enriched = [t for t in data if t.get("details_enriched_at")]
    with_phone = [t for t in data if t.get("phone_number")]
    with_site = [t for t in data if t.get("website_uri")]
    check("T3 Nantes enriched >= 15/21", len(enriched) >= 15, f"enriched={len(enriched)}/21 with_phone={len(with_phone)} with_site={len(with_site)}")


def t4_terraces_lyon():
    r = requests.get(f"{BASE}/terraces?city=Lyon&limit=500", timeout=30)
    check("T4 /terraces?city=Lyon 200", r.status_code == 200)
    if r.status_code != 200:
        return
    body = r.json()
    data = body.get("terraces", body) if isinstance(body, dict) else body
    check("T4 Lyon count >= 280", len(data) >= 280, f"count={len(data)}")
    enriched = [t for t in data if t.get("details_enriched_at")]
    pct = (len(enriched) / len(data) * 100) if data else 0
    check("T4 Lyon >=50% details_enriched_at (majorité)", len(enriched) >= len(data) * 0.5, f"{len(enriched)}/{len(data)} = {pct:.1f}%")
    # leaks
    leaks = [t["id"] for t in data if "shadow_map" in t or "community_photos" in t]
    check("T4 Lyon 0 leak", len(leaks) == 0, f"leaks={leaks[:3]}")


def t5_search_cigale():
    r = requests.get(f"{BASE}/terraces/search", params={"q": "cigale"}, timeout=15)
    check("T5 /search?q=cigale 200", r.status_code == 200)
    if r.status_code != 200:
        return
    data = r.json()
    results = data.get("results", [])
    la_cigale = next((t for t in results if t.get("id") == "81e95a94-271c-4242-bde1-6f764343335a"), None)
    check("T5 search trouve La Cigale", la_cigale is not None, f"results_count={len(results)}")
    if la_cigale:
        check("T5 La Cigale phone via search", la_cigale.get("phone_number") == "+33 2 51 84 94 94", f"got={la_cigale.get('phone_number')}")
        check("T5 La Cigale website via search", la_cigale.get("website_uri") == "http://www.lacigale.com/", f"got={la_cigale.get('website_uri')}")
        check("T5 La Cigale details_enriched_at via search", bool(la_cigale.get("details_enriched_at")))
        check("T5 search 0 shadow_map leak", "shadow_map" not in la_cigale)
        check("T5 search 0 community_photos leak", "community_photos" not in la_cigale)


def t6_crowdsourcing():
    # report
    r = requests.post(f"{BASE}/terraces/81e95a94-271c-4242-bde1-6f764343335a/report", json={"type": "confirmed", "user_id": "nonregtest"}, timeout=15)
    check("T6 POST /report confirmed", r.status_code == 200, f"status={r.status_code}")

    # photo
    tiny_png = base64.b64encode(
        bytes.fromhex("89504E470D0A1A0A0000000D49484452000000010000000108060000001F15C4890000000D49444154789C63000100000005000100A0D8FE0000000049454E44AE426082")
    ).decode()
    r = requests.post(f"{BASE}/terraces/81e95a94-271c-4242-bde1-6f764343335a/photo", json={"image_base64": tiny_png, "user_id": "nonregtest", "caption": "test"}, timeout=15)
    check("T6 POST /photo base64", r.status_code == 200, f"status={r.status_code}")
    photo_id = r.json().get("photo_id") if r.status_code == 200 else None

    # submit
    r = requests.post(f"{BASE}/terraces/submit", json={
        "name": "NonReg Test Bar",
        "type": "bar",
        "orientation_label": "sud",
        "lat": 47.218,
        "lng": -1.553,
        "city": "Nantes",
        "user_id": "nonregtest",
    }, timeout=15)
    check("T6 POST /terraces/submit", r.status_code == 200, f"status={r.status_code}")
    submit_id = r.json().get("id") if r.status_code == 200 else None

    # pro/contact
    r = requests.post(f"{BASE}/pro/contact", json={
        "establishment_name": "NonReg Brasserie",
        "email": "nonreg@example.fr",
        "city": "Nantes",
        "message": "Test non-reg",
    }, timeout=15)
    check("T6 POST /pro/contact", r.status_code == 200, f"status={r.status_code}")
    lead_id = r.json().get("id") if r.status_code == 200 else None

    # next-sunny
    r = requests.get(f"{BASE}/next-sunny?city=Nantes", timeout=15)
    check("T6 /next-sunny?city=Nantes 200", r.status_code == 200, f"status={r.status_code}")

    # sun-position
    r = requests.get(f"{BASE}/sun-position?lat=47.2184&lng=-1.5536", timeout=10)
    check("T6 /sun-position 200", r.status_code == 200)

    # sun-check
    r = requests.post(f"{BASE}/sun-check", json={"lat": 47.2184, "lng": -1.5536, "orientation_degrees": 180}, timeout=10)
    check("T6 /sun-check 200", r.status_code == 200)

    # weather (may be 502, non-blocking)
    r = requests.get(f"{BASE}/weather/Nantes", timeout=15)
    check("T6 /weather/Nantes 200 (accepte 502 rate-limit)", r.status_code in (200, 502), f"status={r.status_code}")

    # Cleanup: via mongo shell
    cleanup_script = f"""
from pymongo import MongoClient
import os
from dotenv import load_dotenv
load_dotenv('/app/backend/.env')
client = MongoClient(os.environ['MONGO_URL'])
db = client.get_default_database()
if '{submit_id}' and '{submit_id}' != 'None':
    print('submit_del=', db.terraces.delete_one({{'id': '{submit_id}'}}).deleted_count)
print('reports_del=', db.reports.delete_many({{'user_id': 'nonregtest'}}).deleted_count)
if '{lead_id}' and '{lead_id}' != 'None':
    print('lead_del=', db.pro_leads.delete_one({{'id': '{lead_id}'}}).deleted_count)
# Pull the test photo from community_photos
if '{photo_id}' and '{photo_id}' != 'None':
    res = db.terraces.update_one({{'id': '81e95a94-271c-4242-bde1-6f764343335a'}}, {{'$pull': {{'community_photos': {{'id': '{photo_id}'}}}}}})
    print('photo_pulled=', res.modified_count)
# Reset reports on La Cigale
db.terraces.update_one({{'id': '81e95a94-271c-4242-bde1-6f764343335a'}}, {{'$set': {{'reports.confirmed': 0, 'reports.wrong_orientation': 0, 'reports.no_terrace': 0}}}})
"""
    import subprocess
    res = subprocess.run(["python3", "-c", cleanup_script], capture_output=True, text=True, timeout=30)
    print(f"  cleanup stdout: {res.stdout.strip()}")
    if res.stderr:
        print(f"  cleanup stderr: {res.stderr.strip()}")


def t7_lieu_unique():
    tid = "57c290ff-05bc-402f-afca-d9e939322808"
    r = requests.get(f"{BASE}/terraces/{tid}", timeout=15)
    check("T7 Le Lieu Unique 200", r.status_code == 200)
    if r.status_code != 200:
        return
    d = r.json()
    check("T7 Le Lieu Unique has details_enriched_at", bool(d.get("details_enriched_at")), f"got={d.get('details_enriched_at')}")
    # Other fields should be null/absent (Google returned empty)
    phone = d.get("phone_number")
    site = d.get("website_uri")
    pl = d.get("price_level")
    oh = d.get("opening_hours")
    print(f"  Le Lieu Unique fields: phone={phone} site={site} price_level={pl} opening_hours={'set' if oh else 'null/absent'}")
    # Acceptable that these are null or absent
    check("T7 shadow_analyzed=true conservé", d.get("shadow_analyzed") is True, f"got={d.get('shadow_analyzed')}")
    check("T7 sun_schedule_today présent", isinstance(d.get("sun_schedule_today"), dict))
    check("T7 hourly_forecast list", isinstance(d.get("hourly_forecast"), list) and len(d["hourly_forecast"]) > 0)
    check("T7 PAS de shadow_map", "shadow_map" not in d)
    check("T7 PAS de community_photos", "community_photos" not in d)


def t8_no_leaks_global():
    """Contract test: shadow_map and community_photos never leak in /terraces, /search, /terraces/{id}."""
    # /terraces for each city
    for city in ["Nantes", "Paris", "Lyon", "Marseille", "Bordeaux"]:
        r = requests.get(f"{BASE}/terraces?city={city}&limit=500", timeout=30)
        if r.status_code != 200:
            check(f"T8 /terraces?city={city} 200", False, f"status={r.status_code}")
            continue
        body = r.json()
        data = body.get("terraces", body) if isinstance(body, dict) else body
        leak_sm = sum(1 for t in data if "shadow_map" in t)
        leak_cp = sum(1 for t in data if "community_photos" in t)
        check(f"T8 {city} no shadow_map leak (n={len(data)})", leak_sm == 0, f"leaks={leak_sm}")
        check(f"T8 {city} no community_photos leak (n={len(data)})", leak_cp == 0, f"leaks={leak_cp}")

    # /search
    for q in ["cigale", "bar", "cafe"]:
        r = requests.get(f"{BASE}/terraces/search", params={"q": q}, timeout=15)
        if r.status_code != 200:
            continue
        results = r.json().get("results", [])
        leak_sm = sum(1 for t in results if "shadow_map" in t)
        leak_cp = sum(1 for t in results if "community_photos" in t)
        check(f"T8 search q={q} no leak", leak_sm == 0 and leak_cp == 0, f"sm={leak_sm} cp={leak_cp}")


def main():
    print(f"\n=== Places Details Enrichment Non-Regression ===")
    print(f"BASE={BASE}\n")
    print("--- T1: /api/cities = 8 villes ---")
    t1_cities()
    print("\n--- T2: La Cigale enrichment ---")
    t2_la_cigale()
    print("\n--- T3: /terraces?city=Nantes ---")
    t3_terraces_nantes()
    print("\n--- T4: /terraces?city=Lyon ---")
    t4_terraces_lyon()
    print("\n--- T5: search ?q=cigale ---")
    t5_search_cigale()
    print("\n--- T6: Non-regression crowdsourcing CRUD + endpoints core ---")
    t6_crowdsourcing()
    print("\n--- T7: Le Lieu Unique (no Google details) ---")
    t7_lieu_unique()
    print("\n--- T8: No leaks in public endpoints ---")
    t8_no_leaks_global()

    print(f"\n\n========== SUMMARY ==========")
    print(f"PASS: {len(PASS)}")
    print(f"FAIL: {len(FAIL)}")
    if FAIL:
        print("\nFailed checks:")
        for lbl, det in FAIL:
            print(f"  - {lbl}: {det}")
    sys.exit(0 if not FAIL else 1)


if __name__ == "__main__":
    main()
