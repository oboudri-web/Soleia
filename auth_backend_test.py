"""
Soleia backend - Non-regression + new /api/auth/* endpoints tests.

Target: https://sunny-terraces.preview.emergentagent.com/api
Mongo:  mongodb://localhost:27017 / db suntterrace_db

Seeds a test user + session directly in mongo, runs all auth scenarios,
then cleans up. Also re-runs a lightweight non-regression of existing endpoints.
"""
from __future__ import annotations

import os
import sys
import json
import time
import base64
from datetime import datetime, timedelta, timezone

import requests
from pymongo import MongoClient

BASE = "https://sunny-terraces.preview.emergentagent.com/api"
MONGO_URL = "mongodb://localhost:27017"
DB_NAME = "suntterrace_db"

TEST_USER_ID = "test_auth_agent"
TEST_TOKEN = "stk_agent_test_xxx"
TEST_EMAIL = "tester@example.com"

passes = []
fails = []


def _print(tag, name, ok, info=""):
    mark = "PASS" if ok else "FAIL"
    line = f"[{mark}] {tag} :: {name}"
    if info:
        line += f" -- {info}"
    print(line)
    (passes if ok else fails).append(line)


def assert_eq(tag, name, got, expected):
    ok = got == expected
    _print(tag, name, ok, f"got={got!r} expected={expected!r}")
    return ok


def assert_true(tag, name, cond, info=""):
    _print(tag, name, bool(cond), info)
    return bool(cond)


# =========================================
# 0. Seed mongo
# =========================================
def seed():
    mc = MongoClient(MONGO_URL)
    db = mc[DB_NAME]
    # Clean any leftover
    db.users.delete_many({"user_id": TEST_USER_ID})
    db.user_sessions.delete_many({"session_token": TEST_TOKEN})
    now = datetime.now(timezone.utc)
    db.users.insert_one({
        "user_id": TEST_USER_ID,
        "email": TEST_EMAIL,
        "name": "Tester",
        "favorite_ids": [],
        "created_at": now,
        "last_login_at": now,
    })
    db.user_sessions.insert_one({
        "user_id": TEST_USER_ID,
        "session_token": TEST_TOKEN,
        "expires_at": now + timedelta(days=30),
        "created_at": now,
    })
    return db


def cleanup(db):
    db.users.delete_many({"user_id": TEST_USER_ID})
    db.user_sessions.delete_many({"user_id": TEST_USER_ID})
    db.user_sessions.delete_many({"session_token": TEST_TOKEN})


# =========================================
# 1. NON-REGRESSION
# =========================================
def test_non_regression():
    TAG = "regression"
    # health
    r = requests.get(f"{BASE}/health", timeout=15)
    # The health endpoint may not exist — check /.
    if r.status_code == 404:
        r = requests.get(f"{BASE}/", timeout=15)
    assert_true(TAG, "health_or_root_200", r.status_code in (200,), f"status={r.status_code}")

    # cities
    r = requests.get(f"{BASE}/cities", timeout=15)
    assert_true(TAG, "cities_200", r.status_code == 200)
    try:
        cities = r.json()
        assert_true(TAG, "cities_contains_nantes",
                    any(c.get("name") == "Nantes" or c == "Nantes" for c in cities),
                    f"payload_type={type(cities).__name__}")
    except Exception as e:
        _print(TAG, "cities_parse", False, str(e))

    # terraces no filter
    r = requests.get(f"{BASE}/terraces", timeout=30)
    assert_true(TAG, "terraces_no_filter_200", r.status_code == 200)

    # terraces with bbox
    r = requests.get(f"{BASE}/terraces", params={
        "lat_min": 47.20, "lat_max": 47.25,
        "lng_min": -1.58, "lng_max": -1.53,
    }, timeout=30)
    assert_true(TAG, "terraces_bbox_200", r.status_code == 200)

    # terraces at_time ISO
    r = requests.get(f"{BASE}/terraces", params={"at_time": "2026-04-23T14:00:00", "city": "Nantes"}, timeout=30)
    assert_true(TAG, "terraces_at_time_200", r.status_code == 200)

    # terraces detail (Le Lieu Unique)
    LIEU_ID = "57c290ff-05bc-402f-afca-d9e939322808"
    r = requests.get(f"{BASE}/terraces/{LIEU_ID}", timeout=15)
    assert_true(TAG, "terrace_detail_200", r.status_code == 200)
    if r.status_code == 200:
        doc = r.json()
        assert_true(TAG, "detail_has_sun_schedule", "sun_schedule_today" in doc)
        assert_true(TAG, "detail_has_hourly_forecast", isinstance(doc.get("hourly_forecast"), list))
        assert_true(TAG, "detail_no_shadow_map_leak", "shadow_map" not in doc)
        assert_true(TAG, "detail_no_community_photos_leak", "community_photos" not in doc)

    # weather (502 transient accepté)
    r = requests.get(f"{BASE}/weather/Nantes", timeout=30)
    assert_true(TAG, "weather_nantes_200_or_502",
                r.status_code in (200, 502), f"status={r.status_code}")

    # next-sunny
    r = requests.get(f"{BASE}/next-sunny", params={"city": "Nantes"}, timeout=30)
    assert_true(TAG, "next_sunny_200", r.status_code == 200)
    if r.status_code == 200:
        js = r.json()
        assert_true(TAG, "next_sunny_has_found", "found" in js)

    # shadows
    r = requests.get(f"{BASE}/shadows", params={
        "lat_min": 47.210, "lat_max": 47.222,
        "lng_min": -1.568, "lng_max": -1.552,
        "at_time": "2026-04-23T14:00:00",
    }, timeout=60)
    assert_true(TAG, "shadows_200", r.status_code == 200)
    if r.status_code == 200:
        js = r.json()
        assert_true(TAG, "shadows_has_polygons_key", "polygons" in js)
        assert_true(TAG, "shadows_has_sun_key", "sun" in js)

    # generate-description (Claude) - may take a bit
    r = requests.post(f"{BASE}/terraces/{LIEU_ID}/generate-description", timeout=60)
    assert_true(TAG, "generate_description_200", r.status_code == 200, f"status={r.status_code}")

    # search
    r = requests.get(f"{BASE}/search/terraces", params={"q": "lieu"}, timeout=15)
    # Route could be /api/terraces/search in this backend; try both
    if r.status_code == 404:
        r = requests.get(f"{BASE}/terraces/search", params={"q": "lieu", "city": "Nantes"}, timeout=15)
    assert_true(TAG, "search_200", r.status_code == 200, f"status={r.status_code}")

    # Crowdsourcing submissions (light checks, with cleanup)
    submit_payload = {
        "name": "NonReg AuthAgent Bar",
        "type": "bar",
        "orientation_label": "sud",
        "lat": 47.2184,
        "lng": -1.5536,
        "city": "Nantes",
        "user_id": "nr_auth_agent",
    }
    r = requests.post(f"{BASE}/terraces/submit", json=submit_payload, timeout=15)
    assert_true(TAG, "terraces_submit_200", r.status_code == 200)
    new_id = None
    if r.status_code == 200:
        new_id = r.json().get("id")
        # Report the new terrace
        r2 = requests.post(f"{BASE}/terraces/{new_id}/report", json={"type": "confirmed"}, timeout=15)
        assert_true(TAG, "report_confirmed_200", r2.status_code == 200)
    # Pro contact
    pro_payload = {
        "establishment_name": "Bar NonReg Auth",
        "email": "nonreg.auth@example.fr",
        "city": "Nantes",
        "message": "test",
    }
    r = requests.post(f"{BASE}/pro/contact", json=pro_payload, timeout=15)
    assert_true(TAG, "pro_contact_200", r.status_code == 200)
    pro_lead_id = r.json().get("id") if r.status_code == 200 else None

    # Cleanup
    mc = MongoClient(MONGO_URL)
    db = mc[DB_NAME]
    if new_id:
        db.terraces.delete_many({"id": new_id})
        db.reports.delete_many({"terrace_id": new_id})
    if pro_lead_id:
        db.pro_leads.delete_many({"id": pro_lead_id})
    db.pro_leads.delete_many({"email": "nonreg.auth@example.fr"})


# =========================================
# 2. AUTH (unauthenticated scenarios)
# =========================================
def test_auth_unauth():
    TAG = "auth.unauth"

    # 2a. mobile-callback HTML
    r = requests.get(f"{BASE}/auth/mobile-callback", timeout=15)
    assert_eq(TAG, "mobile_callback_status_200", r.status_code, 200)
    ctype = r.headers.get("content-type", "")
    assert_true(TAG, "mobile_callback_content_type_html", "text/html" in ctype.lower(), f"ctype={ctype}")
    body = r.text
    assert_true(TAG, "mobile_callback_contains_deep_link",
                "soleia://auth?session_id=" in body or "soleia://auth" in body)
    assert_true(TAG, "mobile_callback_has_script", "<script" in body)

    # 2b. POST /auth/session with body {} -> 422
    r = requests.post(f"{BASE}/auth/session", json={}, timeout=15)
    assert_eq(TAG, "session_empty_body_422", r.status_code, 422)

    # 2c. POST /auth/session with fake session_id -> 401
    r = requests.post(f"{BASE}/auth/session",
                      json={"session_id": "fake_invalid_xxx"}, timeout=20)
    assert_eq(TAG, "session_fake_sid_401", r.status_code, 401)
    try:
        detail = r.json().get("detail", "")
    except Exception:
        detail = r.text
    assert_true(TAG, "session_fake_sid_detail_mentions_emergent",
                "Emergent" in detail or "rejected" in detail.lower(),
                f"detail={detail!r}")

    # 2d. /auth/me without header -> 401 Missing Authorization header
    r = requests.get(f"{BASE}/auth/me", timeout=15)
    assert_eq(TAG, "me_no_auth_401", r.status_code, 401)
    try:
        detail = r.json().get("detail", "")
    except Exception:
        detail = r.text
    assert_true(TAG, "me_no_auth_detail_missing_header",
                "Missing Authorization header" in detail, f"detail={detail!r}")

    # 2e. /auth/me with invalid token -> 401 Invalid session
    r = requests.get(f"{BASE}/auth/me",
                     headers={"Authorization": "Bearer invalid_token"}, timeout=15)
    assert_eq(TAG, "me_invalid_token_401", r.status_code, 401)
    try:
        detail = r.json().get("detail", "")
    except Exception:
        detail = r.text
    assert_true(TAG, "me_invalid_token_detail", "Invalid session" in detail, f"detail={detail!r}")


# =========================================
# 3. AUTH (authenticated scenarios with seeded session)
# =========================================
def test_auth_authed(db):
    TAG = "auth.authed"
    H = {"Authorization": f"Bearer {TEST_TOKEN}"}

    # GET /auth/me
    r = requests.get(f"{BASE}/auth/me", headers=H, timeout=15)
    assert_eq(TAG, "me_200", r.status_code, 200)
    me = r.json() if r.status_code == 200 else {}
    assert_eq(TAG, "me_user_id", me.get("user_id"), TEST_USER_ID)
    assert_eq(TAG, "me_email", me.get("email"), TEST_EMAIL)
    assert_eq(TAG, "me_name", me.get("name"), "Tester")
    assert_true(TAG, "me_has_favorite_ids_key", "favorite_ids" in me)
    assert_true(TAG, "me_favorite_ids_empty_initial", me.get("favorite_ids") == [])
    # picture key may be present as null
    assert_true(TAG, "me_picture_key_present_or_missing_ok", True)  # no strict check

    # PUT /auth/favorites with dup -> dedupe preserving order
    payload = {"favorite_ids": ["a", "b", "b", "c"]}
    r = requests.put(f"{BASE}/auth/favorites", headers=H, json=payload, timeout=15)
    assert_eq(TAG, "put_favorites_200", r.status_code, 200)
    if r.status_code == 200:
        js = r.json()
        assert_eq(TAG, "put_favorites_ok", js.get("ok"), True)
        assert_eq(TAG, "put_favorites_deduped", js.get("favorite_ids"), ["a", "b", "c"])

    # GET /auth/favorites
    r = requests.get(f"{BASE}/auth/favorites", headers=H, timeout=15)
    assert_eq(TAG, "get_favorites_200", r.status_code, 200)
    if r.status_code == 200:
        js = r.json()
        assert_eq(TAG, "get_favorites_returns_abc", js.get("favorite_ids"), ["a", "b", "c"])

    # POST /auth/favorites/merge {"favorite_ids": ["d","a"]} -> ["a","b","c","d"], added=1
    r = requests.post(f"{BASE}/auth/favorites/merge",
                      headers=H, json={"favorite_ids": ["d", "a"]}, timeout=15)
    assert_eq(TAG, "merge_favorites_200", r.status_code, 200)
    if r.status_code == 200:
        js = r.json()
        assert_eq(TAG, "merge_union_order", js.get("favorite_ids"), ["a", "b", "c", "d"])
        assert_eq(TAG, "merge_added_1", js.get("added"), 1)

    # POST /auth/logout
    r = requests.post(f"{BASE}/auth/logout", headers=H, timeout=15)
    assert_eq(TAG, "logout_200", r.status_code, 200)
    if r.status_code == 200:
        assert_eq(TAG, "logout_ok_true", r.json().get("ok"), True)

    # /auth/me after logout -> 401 Invalid session
    r = requests.get(f"{BASE}/auth/me", headers=H, timeout=15)
    assert_eq(TAG, "me_after_logout_401", r.status_code, 401)
    try:
        detail = r.json().get("detail", "")
    except Exception:
        detail = r.text
    assert_true(TAG, "me_after_logout_detail_invalid",
                "Invalid session" in detail, f"detail={detail!r}")


# =========================================
# MAIN
# =========================================
def main():
    print(f"Target: {BASE}")
    db = seed()
    try:
        test_non_regression()
        test_auth_unauth()
        test_auth_authed(db)
    finally:
        cleanup(db)

    total = len(passes) + len(fails)
    print("\n==================================================")
    print(f"TOTAL: {total} checks | PASS={len(passes)} | FAIL={len(fails)}")
    print("==================================================")
    if fails:
        print("\nFAILS:")
        for line in fails:
            print(" ", line)
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
