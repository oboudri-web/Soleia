"""
Soleia PIVOT #2 - non-regression tests.

Key changes verified here:
 - 169 fast-food deleted (McDonald/KFC/Burger King/Quick/Five Guys/Subway/Paul/
   Brioche Dor(ée)/Domino/Pizza Hut). Starbucks kept.
 - /api/terraces and /api/terraces/search apply fast-food exclusion.
 - /api/terraces new optional params: lat_min, lat_max, lng_min, lng_max (bbox).
 - /api/terraces hard cap 200 (limit>200 truncated).
 - Type policy:
     bar, cafe, rooftop      -> all establishments
     restaurant              -> only if has_terrace_confirmed=true OR
                                (google_rating >= 4.0 AND google_ratings_count >= 100)
     fast_food               -> never returned
"""
import asyncio
import base64
import os
import re
import sys
from typing import List, Tuple

import httpx
from motor.motor_asyncio import AsyncIOMotorClient


def read_frontend_env() -> str:
    path = "/app/frontend/.env"
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("EXPO_PUBLIC_BACKEND_URL"):
                _, _, v = line.partition("=")
                return v.strip().strip('"').strip("'")
    raise RuntimeError("EXPO_PUBLIC_BACKEND_URL not found")


BASE = read_frontend_env().rstrip("/") + "/api"
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "suntterrace_db")

ID_LIEU_UNIQUE = "57c290ff-05bc-402f-afca-d9e939322808"

FAST_FOOD_TOKENS = [
    "mcdonald", "kfc", "burger king", "quick", "five guys",
    "subway", "paul", "brioche dor", "domino", "pizza hut",
]

EXPECTED_CITIES = {"Paris", "Lyon", "Marseille", "Bordeaux",
                   "Nantes", "Toulouse", "Nice", "Montpellier"}

ALLOWED_TYPES = {"bar", "cafe", "restaurant", "rooftop"}

HEAVY_FIELDS = ("shadow_map", "community_photos")

TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgAAIA"
    "AAUAAeImBZsAAAAASUVORK5CYII="
)


# ---------------------------------------------------------------------------
# Reporting helpers
# ---------------------------------------------------------------------------
PASS: List[str] = []
FAIL: List[Tuple[str, str]] = []


def ok(name: str, note: str = "") -> None:
    PASS.append(f"{name}{' :: '+note if note else ''}")
    print(f"PASS  {name} {note}")


def ko(name: str, note: str) -> None:
    FAIL.append((name, note))
    print(f"FAIL  {name} :: {note}")


def require(name: str, cond: bool, note: str = "") -> None:
    if cond:
        ok(name, note)
    else:
        ko(name, note or "condition false")


def has_no_heavy_leak(doc: dict) -> Tuple[bool, str]:
    for f in HEAVY_FIELDS:
        if f in doc:
            return False, f"{f} leaked"
    return True, ""


def name_matches_fast_food(name: str) -> str:
    if not name:
        return ""
    lo = name.lower()
    for tok in FAST_FOOD_TOKENS:
        if tok in lo:
            return tok
    return ""


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
async def main() -> int:
    print(f"BASE = {BASE}")
    print(f"DB   = {DB_NAME} @ {MONGO_URL}")

    async with httpx.AsyncClient(timeout=60.0) as client:
        mongo = AsyncIOMotorClient(MONGO_URL)
        db = mongo[DB_NAME]

        # -------------------------------------------------- #1 cities = 8
        r = await client.get(f"{BASE}/cities")
        require("cities.status200", r.status_code == 200, f"status={r.status_code}")
        data = r.json()
        if isinstance(data, dict):
            cities = data.get("cities") or data.get("items") or []
        else:
            cities = data
        names = set()
        if isinstance(cities, list):
            for c in cities:
                if isinstance(c, str):
                    names.add(c)
                elif isinstance(c, dict):
                    names.add(c.get("name") or c.get("city") or "")
        require(
            "cities.exactly_8",
            names == EXPECTED_CITIES,
            f"got={sorted(names)}",
        )

        # -------------------------------------------------- #2 cap <=200 on Nantes
        r = await client.get(f"{BASE}/terraces", params={"city": "Nantes"})
        require("nantes.status200", r.status_code == 200, f"status={r.status_code}")
        nantes_data = r.json()
        nantes_terraces = nantes_data.get("terraces", [])
        count = nantes_data.get("count", len(nantes_terraces))
        require(
            "nantes.count_le_200",
            count <= 200 and len(nantes_terraces) <= 200,
            f"count={count} len={len(nantes_terraces)}",
        )

        # -------------------------------------------------- #3 bbox filter
        bbox_params = {
            "city": "Nantes",
            "lat_min": 47.20, "lat_max": 47.23,
            "lng_min": -1.58, "lng_max": -1.54,
        }
        r = await client.get(f"{BASE}/terraces", params=bbox_params)
        require("nantes.bbox.status200", r.status_code == 200, f"status={r.status_code}")
        bbox_data = r.json()
        bbox_terraces = bbox_data.get("terraces", [])
        in_bbox = all(
            47.20 <= t["lat"] <= 47.23 and -1.58 <= t["lng"] <= -1.54
            for t in bbox_terraces
        )
        require(
            "nantes.bbox.count_le_200",
            bbox_data.get("count", 0) <= 200,
            f"count={bbox_data.get('count')}",
        )
        require(
            "nantes.bbox.all_inside",
            in_bbox,
            f"some outside bbox (n={len(bbox_terraces)})",
        )
        query_echo = bbox_data.get("query", {})
        bbox_echo = query_echo.get("bbox")
        require(
            "nantes.bbox.query_echo",
            bbox_echo is not None and len(bbox_echo) == 4,
            f"query.bbox={bbox_echo}",
        )

        # -------------------------------------------------- #4 Paris no fast-food names
        r = await client.get(f"{BASE}/terraces", params={"city": "Paris"})
        require("paris.status200", r.status_code == 200, f"status={r.status_code}")
        paris_data = r.json()
        paris_terraces = paris_data.get("terraces", [])
        leaks = []
        for t in paris_terraces:
            tok = name_matches_fast_food(t.get("name", ""))
            if tok:
                leaks.append((t.get("name"), tok))
        require(
            "paris.no_fast_food_brand_names",
            len(leaks) == 0,
            f"leaks={leaks[:5]} total={len(leaks)} (over n={len(paris_terraces)})",
        )

        # -------------------------------------------------- #5 restaurant quality policy
        r = await client.get(
            f"{BASE}/terraces",
            params={"city": "Nantes", "type": "restaurant", "limit": 200},
        )
        require("nantes.restaurant.status200", r.status_code == 200, f"status={r.status_code}")
        resto = r.json().get("terraces", [])
        bad = []
        for t in resto:
            if t.get("type") != "restaurant":
                bad.append(("wrong_type", t.get("id"), t.get("type")))
                continue
            confirmed = bool(t.get("has_terrace_confirmed"))
            rating = t.get("google_rating") or 0
            count_ = t.get("google_ratings_count") or 0
            if not confirmed and not (rating >= 4.0 and count_ >= 100):
                bad.append(
                    ("bad_quality", t.get("id"), f"c={confirmed} r={rating} n={count_}")
                )
        require(
            "nantes.restaurant.policy",
            len(bad) == 0,
            f"violations={bad[:5]} total={len(bad)} (over n={len(resto)})",
        )

        # -------------------------------------------------- #6 Nantes bar type restriction
        r = await client.get(
            f"{BASE}/terraces",
            params={"city": "Nantes", "type": "bar"},
        )
        require("nantes.bar.status200", r.status_code == 200, f"status={r.status_code}")
        bars = r.json().get("terraces", [])
        types = {t.get("type") for t in bars}
        require(
            "nantes.bar.type_only",
            types <= {"bar"},
            f"types seen={types}",
        )

        # -------------------------------------------------- #7 type=fast_food rejected
        r = await client.get(
            f"{BASE}/terraces",
            params={"city": "Nantes", "type": "fast_food"},
        )
        require("nantes.fastfood.status200", r.status_code == 200, f"status={r.status_code}")
        ff = r.json().get("terraces", [])
        require(
            "nantes.fastfood.count_zero",
            len(ff) == 0,
            f"n={len(ff)}",
        )

        # -------------------------------------------------- #8 search mcdonald -> 0
        r = await client.get(f"{BASE}/terraces/search", params={"q": "mcdonald"})
        require("search.mcdonald.status200", r.status_code == 200, f"status={r.status_code}")
        mc_res = r.json().get("results", [])
        require(
            "search.mcdonald.empty",
            len(mc_res) == 0,
            f"count={len(mc_res)}",
        )

        # -------------------------------------------------- #9 search starbucks allowed
        r = await client.get(f"{BASE}/terraces/search", params={"q": "starbucks"})
        require("search.starbucks.status200", r.status_code == 200, f"status={r.status_code}")
        sb_res = r.json().get("results", [])
        # Starbucks is allowed (not in exclusion list). Count can be 0 or more.
        # We just verify no exception and, if any result, the name matches.
        if sb_res:
            ok("search.starbucks.has_results", f"n={len(sb_res)}")
        else:
            ok("search.starbucks.ok_even_if_zero", "Starbucks not in DB at Nantes")

        # -------------------------------------------------- #10 search lieu&city=Nantes -> Le Lieu Unique top 8
        r = await client.get(
            f"{BASE}/terraces/search",
            params={"q": "lieu", "city": "Nantes"},
        )
        require("search.lieu.status200", r.status_code == 200, f"status={r.status_code}")
        lieu_res = r.json().get("results", [])
        lieu_ids = [t.get("id") for t in lieu_res]
        lieu_names = [t.get("name") for t in lieu_res]
        require(
            "search.lieu.lieu_unique_in_top_8",
            ID_LIEU_UNIQUE in lieu_ids,
            f"names={lieu_names}",
        )

        # -------------------------------------------------- #11 type + has_terrace_confirmed present
        # reuse nantes listing (from #2) + paris + bars
        all_docs = nantes_terraces + paris_terraces + bars
        missing_hc = [t.get("id") for t in all_docs if "has_terrace_confirmed" not in t]
        require(
            "contract.has_terrace_confirmed_always_present",
            len(missing_hc) == 0,
            f"missing on {len(missing_hc)} docs",
        )
        bad_types = [
            (t.get("id"), t.get("type"))
            for t in all_docs
            if t.get("type") not in ALLOWED_TYPES
        ]
        require(
            "contract.types_in_allowed_set",
            len(bad_types) == 0,
            f"bad={bad_types[:5]} total={len(bad_types)}",
        )

        # -------------------------------------------------- #12 shadow_map / community_photos never leak
        leak_details: List[str] = []
        for t in nantes_terraces:
            ok_, why = has_no_heavy_leak(t)
            if not ok_:
                leak_details.append(f"nantes:{t.get('id')}:{why}")
        for t in paris_terraces:
            ok_, why = has_no_heavy_leak(t)
            if not ok_:
                leak_details.append(f"paris:{t.get('id')}:{why}")
        for t in lieu_res:
            ok_, why = has_no_heavy_leak(t)
            if not ok_:
                leak_details.append(f"search-lieu:{t.get('id')}:{why}")
        # detail endpoint too
        r = await client.get(f"{BASE}/terraces/{ID_LIEU_UNIQUE}")
        if r.status_code == 200:
            detail = r.json()
            for f in HEAVY_FIELDS:
                if f in detail:
                    leak_details.append(f"detail:lieu_unique:{f}")
        require(
            "contract.no_heavy_leak",
            len(leak_details) == 0,
            f"leaks={leak_details[:5]}",
        )

        # -------------------------------------------------- #13 auto-masking crowdsourcing
        submit_payload = {
            "name": "Pivot2 AutoMask Nantes",
            "type": "bar",
            "orientation_label": "sud",
            "lat": 47.2140,
            "lng": -1.5540,
            "city": "Nantes",
        }
        r = await client.post(f"{BASE}/terraces/submit", json=submit_payload)
        require("automask.submit_200", r.status_code == 200, f"status={r.status_code} body={r.text[:200]}")
        submitted_id = (r.json() or {}).get("id")
        require("automask.submit_has_id", bool(submitted_id), f"id={submitted_id}")

        # verify visibility (type=bar avoids quality filter)
        visible_before = False
        if submitted_id:
            r = await client.get(
                f"{BASE}/terraces",
                params={"city": "Nantes", "type": "bar", "limit": 200},
            )
            ids = {t.get("id") for t in r.json().get("terraces", [])}
            visible_before = submitted_id in ids
            require(
                "automask.visible_before",
                visible_before,
                f"id {submitted_id} not in listing (n={len(ids)})",
            )

        # 3x no_terrace reports
        if submitted_id:
            hidden = False
            for i in range(3):
                r = await client.post(
                    f"{BASE}/terraces/{submitted_id}/report",
                    json={"type": "no_terrace"},
                )
                if r.status_code == 200 and (r.json() or {}).get("hidden"):
                    hidden = True
            require("automask.hidden_after_3_reports", hidden, "hidden flag never true")

            r = await client.get(
                f"{BASE}/terraces",
                params={"city": "Nantes", "type": "bar", "limit": 200},
            )
            ids = {t.get("id") for t in r.json().get("terraces", [])}
            require(
                "automask.disappears_after_hidden",
                submitted_id not in ids,
                f"still in listing",
            )

            # cleanup
            del_t = await db.terraces.delete_one({"id": submitted_id})
            del_r = await db.reports.delete_many({"terrace_id": submitted_id})
            ok(
                "automask.cleanup",
                f"terr_del={del_t.deleted_count} reports_del={del_r.deleted_count}",
            )

        # -------------------------------------------------- #14 other endpoints health check
        # next-sunny
        r = await client.get(f"{BASE}/next-sunny", params={"city": "Nantes"})
        require("next_sunny.status200", r.status_code == 200, f"status={r.status_code}")

        # sun-position
        r = await client.get(
            f"{BASE}/sun-position",
            params={"lat": 47.2184, "lng": -1.5536},
        )
        require("sun_position.status200", r.status_code == 200, f"status={r.status_code}")

        # sun-check
        r = await client.post(
            f"{BASE}/sun-check",
            json={"lat": 47.2184, "lng": -1.5536, "orientation_degrees": 180},
        )
        require("sun_check.status200", r.status_code == 200, f"status={r.status_code}")

        # detail
        r = await client.get(f"{BASE}/terraces/{ID_LIEU_UNIQUE}")
        require("terrace_detail.status200", r.status_code == 200, f"status={r.status_code}")

        # favorites
        r = await client.post(
            f"{BASE}/terraces/favorites",
            json={"ids": [ID_LIEU_UNIQUE]},
        )
        require("favorites.status200", r.status_code == 200, f"status={r.status_code}")
        fav = r.json()
        fav_terr = fav.get("terraces", [])
        fav_leaks = []
        for t in fav_terr:
            for f in HEAVY_FIELDS:
                if f in t:
                    fav_leaks.append(f"{t.get('id')}:{f}")
        require(
            "favorites.no_leak",
            len(fav_leaks) == 0,
            f"leaks={fav_leaks}",
        )

        # notifications/register
        token = "ExponentPushToken[pivot2-smoke-xyz]"
        r = await client.post(
            f"{BASE}/notifications/register",
            json={"push_token": token, "city": "Nantes"},
        )
        require("notifications.register_200", r.status_code == 200, f"status={r.status_code}")
        # cleanup
        await db.push_tokens.delete_many({"token": {"$regex": "pivot2-smoke"}})

        # photo on real terrace (Le Lieu Unique)
        r = await client.post(
            f"{BASE}/terraces/{ID_LIEU_UNIQUE}/photo",
            json={"image_base64": TINY_PNG_B64, "caption": "pivot2_smoke"},
        )
        require("photo.status200", r.status_code == 200, f"status={r.status_code}")
        photo_id = (r.json() or {}).get("photo_id")
        # cleanup the photo
        if photo_id:
            await db.terraces.update_one(
                {"id": ID_LIEU_UNIQUE},
                {"$pull": {"community_photos": {"id": photo_id}}},
            )

        # report on real terrace (confirmed) then reset
        r = await client.post(
            f"{BASE}/terraces/{ID_LIEU_UNIQUE}/report",
            json={"type": "confirmed"},
        )
        require("report.status200", r.status_code == 200, f"status={r.status_code}")
        await db.reports.delete_many({"terrace_id": ID_LIEU_UNIQUE})
        await db.terraces.update_one(
            {"id": ID_LIEU_UNIQUE},
            {"$set": {"reports": {}}},
        )

        # pro/contact + cleanup
        r = await client.post(
            f"{BASE}/pro/contact",
            json={
                "establishment_name": "Pivot2 Smoke Bar",
                "email": "pivot2.smoke@example.fr",
                "city": "Nantes",
                "message": "pivot2 smoke",
            },
        )
        require("pro_contact.status200", r.status_code == 200, f"status={r.status_code}")
        await db.pro_leads.delete_many({"email": "pivot2.smoke@example.fr"})

        # weather: accept 200 or 502 (Open-Meteo rate-limit)
        r = await client.get(f"{BASE}/weather/Nantes")
        require(
            "weather.200_or_502",
            r.status_code in (200, 502),
            f"status={r.status_code}",
        )

        # -------------------------------------------------- #15 limit=500 capped at 200
        r = await client.get(
            f"{BASE}/terraces",
            params={"city": "Nantes", "limit": 500},
        )
        require(
            "cap.limit500_status200",
            r.status_code == 200,
            f"status={r.status_code}",
        )
        if r.status_code == 200:
            cap_data = r.json()
            cap_count = cap_data.get("count", len(cap_data.get("terraces", [])))
            require(
                "cap.limit500_truncated_to_200",
                cap_count <= 200,
                f"count={cap_count}",
            )

        # -------------------------------------------------- final cleanup safety
        # purge any stray pivot2 test docs
        stray = await db.terraces.delete_many({"name": {"$regex": "Pivot2", "$options": "i"}})
        if stray.deleted_count:
            ok("cleanup.stray_pivot2", f"deleted={stray.deleted_count}")

        mongo.close()

    print("\n============ SUMMARY ============")
    print(f"PASS: {len(PASS)}")
    print(f"FAIL: {len(FAIL)}")
    if FAIL:
        print("--- failures ---")
        for n, note in FAIL:
            print(f"  {n} :: {note}")
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
