"""
Non-régression rapide Soleia - 14 checks pendant que 3 batchs tournent en parallèle
(shadow Lyon, vision Toulouse, pipeline Paris: seed-done + vision in-progress).

Counts Paris/Toulouse peuvent grandir pendant le test (vision in progress) — NORMAL.
"""
import os
import sys
import base64
import concurrent.futures
import requests

BASE = os.environ.get("TEST_BACKEND_URL", "https://sunny-terraces.preview.emergentagent.com") + "/api"
TIMEOUT = 30

results = []


def record(name, ok, detail=""):
    results.append((name, ok, detail))
    tag = "PASS" if ok else "FAIL"
    print(f"[{tag}] {name} :: {detail}")


def get(path, **params):
    return requests.get(f"{BASE}{path}", params=params, timeout=TIMEOUT)


def post(path, json_body):
    return requests.post(f"{BASE}{path}", json=json_body, timeout=TIMEOUT)


# ---- test 1 ----
def test_cities():
    try:
        r = get("/cities")
        assert r.status_code == 200, f"status={r.status_code}"
        data = r.json()
        # response is list[{name,lat,lng}] directly
        names = [c["name"] for c in data]
        expected = {"Paris", "Lyon", "Marseille", "Bordeaux", "Nantes", "Toulouse", "Nice", "Montpellier"}
        got = set(names)
        assert got == expected, f"expected {expected}, got {got}"
        assert len(names) == 8, f"len={len(names)}"
        record("1. /cities -> 8 villes exactes", True, f"cities={names}")
    except Exception as e:
        record("1. /cities -> 8 villes exactes", False, str(e))


def _terraces_list(resp_json):
    if isinstance(resp_json, list):
        return resp_json
    return resp_json.get("terraces", [])


# ---- test 2 ----
def test_paris():
    try:
        r = get("/terraces", city="Paris")
        assert r.status_code == 200
        terrs = _terraces_list(r.json())
        assert len(terrs) >= 30, f"count={len(terrs)} (<30)"
        leaks = [t["id"] for t in terrs if "shadow_map" in t]
        assert len(leaks) == 0, f"shadow_map leaks on {len(leaks)} docs"
        missing = [t.get("id") for t in terrs if "sun_status" not in t or "is_sunny" not in t or "shadow_analyzed" not in t]
        assert len(missing) == 0, f"{len(missing)} docs without sun_status/is_sunny/shadow_analyzed"
        shadow_true = sum(1 for t in terrs if t.get("shadow_analyzed") is True)
        record(
            "2. /terraces?city=Paris >=30, sun/shadow fields set, no shadow_map leak",
            True,
            f"count={len(terrs)}, shadow_true={shadow_true}",
        )
    except Exception as e:
        record("2. /terraces?city=Paris >=30", False, str(e))


# ---- test 3 ----
def test_nantes():
    try:
        r = get("/terraces", city="Nantes")
        assert r.status_code == 200
        terrs = _terraces_list(r.json())
        assert len(terrs) == 21, f"got {len(terrs)} (expected 21)"
        shadow_true = sum(1 for t in terrs if t.get("shadow_analyzed") is True)
        assert shadow_true == 21, f"only {shadow_true}/21 shadow_analyzed=true"
        leaks = [t["id"] for t in terrs if "shadow_map" in t]
        assert len(leaks) == 0
        record("3. /terraces?city=Nantes == 21 & 100% shadow_analyzed", True, "21/21 shadow_analyzed=true, no leak")
    except Exception as e:
        record("3. /terraces?city=Nantes 21 & shadow 100%", False, str(e))


# ---- test 4 ----
def test_lyon():
    try:
        r = get("/terraces", city="Lyon")
        assert r.status_code == 200
        terrs = _terraces_list(r.json())
        assert len(terrs) >= 280, f"count={len(terrs)}"
        leaks = [t for t in terrs if "shadow_map" in t]
        assert len(leaks) == 0
        shadow_true = sum(1 for t in terrs if t.get("shadow_analyzed") is True)
        record("4. /terraces?city=Lyon >=280", True, f"count={len(terrs)}, shadow_true={shadow_true}")
    except Exception as e:
        record("4. /terraces?city=Lyon >=280", False, str(e))


# ---- test 5 ----
def test_lieu_unique_detail():
    tid = "57c290ff-05bc-402f-afca-d9e939322808"
    try:
        r = get(f"/terraces/{tid}")
        assert r.status_code == 200, f"status={r.status_code}"
        d = r.json()
        assert d.get("shadow_analyzed") is True, "shadow_analyzed != true"
        assert d.get("shadow_buildings_count") == 97, f"buildings={d.get('shadow_buildings_count')}"
        assert "sun_schedule_today" in d, "no sun_schedule_today"
        hf = d.get("hourly_forecast") or []
        assert len(hf) > 0, "empty hourly_forecast"
        assert "shadow_map" not in d, "shadow_map leak in /terraces/{id}"
        record(
            "5. /terraces/{LieuUnique} détail OK",
            True,
            f"shadow_buildings=97, hourly={len(hf)}h, schedule+forecast present, no leak",
        )
    except Exception as e:
        record("5. /terraces/{LieuUnique}", False, str(e))


# ---- test 6 ----
def test_search_lieu():
    try:
        r = get("/terraces/search", q="lieu", city="Nantes")
        assert r.status_code == 200
        d = r.json()
        res = d.get("results", [])
        assert len(res) == 1, f"got {len(res)} results"
        assert "lieu" in res[0]["name"].lower()
        assert "shadow_map" not in res[0]
        record("6. /search?q=lieu&city=Nantes -> 1 result", True, f"name={res[0]['name']}")
    except Exception as e:
        record("6. /search?q=lieu&city=Nantes", False, str(e))


# ---- test 7 ----
def test_search_cafe():
    try:
        r = get("/terraces/search", q="cafe")
        assert r.status_code == 200
        d = r.json()
        res = d.get("results", [])
        assert len(res) >= 1, "0 results"
        missing = [x for x in res if "sun_status" not in x]
        assert len(missing) == 0
        leaks = [x for x in res if "shadow_map" in x]
        assert len(leaks) == 0
        record("7. /search?q=cafe (no city) -> >=1, all sun_status", True, f"count={len(res)}")
    except Exception as e:
        record("7. /search?q=cafe", False, str(e))


# ---- test 8 ----
def test_next_sunny_nantes():
    try:
        r = get("/next-sunny", city="Nantes")
        assert r.status_code == 200
        d = r.json()
        assert d.get("found") is True, f"found={d.get('found')}"
        record(
            "8. /next-sunny?city=Nantes found=true",
            True,
            f"name={d.get('terrace_name')}, time={d.get('first_sunny_time')}, tomorrow={d.get('is_tomorrow')}",
        )
    except Exception as e:
        record("8. /next-sunny?city=Nantes", False, str(e))


# ---- test 9 ----
def test_sun_position():
    try:
        # Nantes coords (endpoint requires lat+lng, not city)
        r = get("/sun-position", lat=47.2184, lng=-1.5536)
        assert r.status_code == 200, f"status={r.status_code}"
        d = r.json()
        pos = d.get("position", d)
        az = pos.get("azimuth", pos.get("sun_azimuth"))
        alt = pos.get("altitude", pos.get("sun_altitude"))
        assert az is not None and alt is not None, f"missing azimuth/altitude in {pos}"
        record("9. /sun-position (Nantes lat/lng)", True, f"az={az:.1f}, alt={alt:.1f}")
    except Exception as e:
        record("9. /sun-position", False, str(e))


# ---- test 10 ----
def test_sun_check():
    try:
        # server.py contract: POST /sun-check {lat,lng,orientation_degrees}
        r = post("/sun-check", {"lat": 47.2184, "lng": -1.5536, "orientation_degrees": 180})
        assert r.status_code == 200, f"status={r.status_code} body={r.text[:200]}"
        d = r.json()
        assert "is_sunny" in d
        record("10. POST /sun-check (lat/lng/ori=180)", True, f"is_sunny={d['is_sunny']}")
    except Exception as e:
        record("10. /sun-check", False, str(e))


# ---- test 11 ----
def test_weather_nantes():
    try:
        r = get("/weather/Nantes")
        if r.status_code == 200:
            record("11. /weather/Nantes (200)", True, f"temp={r.json().get('temp_c')}")
        elif r.status_code == 502:
            record("11. /weather/Nantes (502 externe, non-bloquant)", True, "Open-Meteo rate-limit accepté")
        else:
            record("11. /weather/Nantes", False, f"unexpected status {r.status_code}")
    except Exception as e:
        record("11. /weather/Nantes", False, str(e))


# ---- test 14 ----
def test_strasbourg():
    try:
        r = get("/terraces", city="Strasbourg")
        assert r.status_code == 200, f"status {r.status_code}"
        terrs = _terraces_list(r.json())
        assert len(terrs) == 0, f"got {len(terrs)}"
        record("14. /terraces?city=Strasbourg -> 200 + 0", True, "empty, no crash")
    except Exception as e:
        record("14. /terraces?city=Strasbourg", False, str(e))


# ---- test 13 ----
def test_concurrent_nantes():
    try:
        def fetch(_):
            r = requests.get(f"{BASE}/terraces", params={"city": "Nantes"}, timeout=TIMEOUT)
            return r.status_code
        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as ex:
            codes = list(ex.map(fetch, range(20)))
        bad = [c for c in codes if c != 200]
        assert len(bad) == 0, f"non-200: {bad}"
        record("13. 20 concurrent GET /terraces?city=Nantes", True, "20/20 = 200")
    except Exception as e:
        record("13. Robustesse concurrente", False, str(e))


# ---- test 12: Crowdsourcing CRUD + cleanup ----
def _mongo_cleanup():
    try:
        from pymongo import MongoClient
        env = {}
        with open("/app/backend/.env") as f:
            for line in f:
                if "=" in line and not line.strip().startswith("#"):
                    k, v = line.strip().split("=", 1)
                    env[k] = v.strip().strip('"').strip("'")
        cli = MongoClient(env["MONGO_URL"])
        return cli[env["DB_NAME"]]
    except Exception as e:
        print(f"(mongo cleanup unavailable: {e})")
        return None


def test_crowdsourcing():
    db = _mongo_cleanup()
    try:
        # pick a terrace in Nantes that is NOT Le Lieu Unique
        r = get("/terraces", city="Nantes")
        terrs = _terraces_list(r.json())
        lieu_id = "57c290ff-05bc-402f-afca-d9e939322808"
        target = next((t for t in terrs if t["id"] != lieu_id), None)
        assert target, "no target terrace"
        tid = target["id"]

        # POST /report
        rp = post(f"/terraces/{tid}/report", {"type": "confirmed"})
        assert rp.status_code == 200, f"/report status {rp.status_code}"
        record("12a. POST /report (confirmed)", True, f"ok={rp.json().get('ok')}")

        # POST /photo (1x1 PNG)
        tiny_png_hex = (
            "89504E470D0A1A0A0000000D49484452000000010000000108060000001F15C4890000"
            "000A49444154789C6300010000000500010D0A2DB40000000049454E44AE426082"
        )
        tiny_b64 = base64.b64encode(bytes.fromhex(tiny_png_hex)).decode()
        pp = post(f"/terraces/{tid}/photo", {"image_base64": tiny_b64, "caption": "NR test"})
        assert pp.status_code == 200, f"/photo status {pp.status_code}"
        photo_id = pp.json().get("photo_id")
        record("12b. POST /photo tiny base64", True, f"photo_id={photo_id}")

        # POST /terraces/submit
        sp = post("/terraces/submit", {
            "name": "Bar Soleia Test NR2026",
            "type": "bar",
            "orientation_label": "sud",
            "lat": 47.2184,
            "lng": -1.5536,
            "city": "Nantes",
        })
        assert sp.status_code == 200
        new_id = sp.json().get("id")
        record("12c. POST /terraces/submit", True, f"id={new_id}")

        # POST /pro/contact
        cp = post("/pro/contact", {
            "establishment_name": "Bar Soleil NR",
            "email": "pro-nr2026@test.fr",
            "city": "Nantes",
            "message": "Test non-régression",
        })
        assert cp.status_code == 200, f"/pro/contact status {cp.status_code}"
        record("12d. POST /pro/contact", True, f"id={cp.json().get('id')}")

        # Cleanup via mongo
        if db is not None:
            dres = db.terraces.delete_one({"id": new_id})
            rres = db.reports.delete_many({"terrace_id": tid, "type": "confirmed"})
            # reset aggregate counter on target so we don't pollute state
            db.terraces.update_one(
                {"id": tid},
                {"$pull": {"community_photos": {"id": photo_id}}, "$inc": {"reports.confirmed": -1}},
            )
            lead_del = db.pro_leads.delete_one({"email": "pro-nr2026@test.fr"})
            record(
                "12e. Cleanup (submit+report+photo+pro_lead)",
                True,
                f"submit_del={dres.deleted_count}, report_del={rres.deleted_count}, pro_del={lead_del.deleted_count}",
            )
        else:
            record("12e. Cleanup", False, "mongo unavailable — manual cleanup needed")
    except Exception as e:
        record("12. Crowdsourcing CRUD", False, str(e))


# ---- extra: shadow_map never exposed ----
def test_no_shadow_map_leak_global():
    try:
        leaks = []
        for city in ["Nantes", "Paris", "Lyon"]:
            r = get("/terraces", city=city)
            if r.status_code == 200:
                for t in _terraces_list(r.json()):
                    if "shadow_map" in t:
                        leaks.append((city, t.get("id")))
        for q in ["lieu", "cafe", "bar"]:
            r = get("/terraces/search", q=q)
            if r.status_code == 200:
                for x in r.json().get("results", []):
                    if "shadow_map" in x:
                        leaks.append((f"search-{q}", x.get("id")))
        assert len(leaks) == 0, f"leaks: {leaks[:5]}"
        record("EX. shadow_map never exposed", True, "0 leaks across Nantes/Paris/Lyon + search")
    except Exception as e:
        record("EX. shadow_map never exposed", False, str(e))


def main():
    print(f"=== Soleia Non-Régression Smoke ===")
    print(f"BASE = {BASE}\n")
    test_cities()
    test_paris()
    test_nantes()
    test_lyon()
    test_lieu_unique_detail()
    test_search_lieu()
    test_search_cafe()
    test_next_sunny_nantes()
    test_sun_position()
    test_sun_check()
    test_weather_nantes()
    test_crowdsourcing()
    test_concurrent_nantes()
    test_strasbourg()
    test_no_shadow_map_leak_global()

    print("\n=== RÉSUMÉ ===")
    total = len(results)
    passed = sum(1 for _, ok, _ in results if ok)
    print(f"PASS: {passed}/{total}")
    for name, ok, detail in results:
        tag = "OK" if ok else "KO"
        print(f"  [{tag}] {name} - {detail}")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
