"""
Soleia non-regression test after PIVOT "show all establishments".

Key change: /api/terraces and /api/terraces/search no longer filter by
has_terrace_confirmed=true. Everything is returned except docs with
terrace_source in ['street_view_no_image', 'community_hidden'].
has_terrace_confirmed field stays exposed on every terrace.

Thresholds:
 - Nantes   > 200 (with >=80 confirmed AND >=500 unconfirmed)
 - Paris    > 500
 - Lyon     > 700
 - Toulouse > 300
 - Nice     > 200
"""
import asyncio
import os
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
ID_LA_CIGALE = "81e95a94-271c-4242-bde1-6f764343335a"

TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)

results: List[Tuple[str, bool, str]] = []


def rec(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name} :: {detail}")


def _extract_terraces(payload) -> list:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("terraces", "results", "items"):
            if isinstance(payload.get(key), list):
                return payload[key]
    return []


async def test_cities(client: httpx.AsyncClient) -> None:
    r = await client.get(f"{BASE}/cities")
    if r.status_code != 200:
        rec("cities.200", False, f"status={r.status_code}")
        return
    cities = r.json()
    expected = {"Paris", "Lyon", "Marseille", "Bordeaux", "Nantes", "Toulouse", "Nice", "Montpellier"}
    names = set()
    for c in cities:
        if isinstance(c, str):
            names.add(c)
        elif isinstance(c, dict):
            for key in ("name", "city", "id"):
                if key in c:
                    names.add(c[key])
                    break
    rec(
        "cities.exact_8",
        len(cities) == 8 and expected == names,
        f"count={len(cities)} names={sorted(names)}",
    )


async def test_terraces_counts_pivot(client: httpx.AsyncClient) -> None:
    """After pivot, counts explode and each doc must expose has_terrace_confirmed."""
    targets = {
        "Nantes": 200,
        "Paris": 500,
        "Lyon": 700,
        "Toulouse": 300,
        "Nice": 200,
    }
    for city, min_count in targets.items():
        r = await client.get(f"{BASE}/terraces", params={"city": city})
        if r.status_code != 200:
            rec(f"terraces.{city.lower()}.pivot_count", False, f"status={r.status_code}")
            continue
        d = r.json()
        ts = _extract_terraces(d) or d.get("terraces", [])
        n = len(ts)
        # has_terrace_confirmed must be present (True or False, not missing) on every doc
        has_field = sum(1 for t in ts if "has_terrace_confirmed" in t and isinstance(t["has_terrace_confirmed"], bool))
        shadow_leak = any("shadow_map" in t for t in ts)
        photos_leak = any("community_photos" in t for t in ts)
        terrace_source_ok = all(
            t.get("terrace_source") not in ("street_view_no_image", "community_hidden")
            for t in ts
        )
        rec(
            f"terraces.{city.lower()}.pivot_count",
            n > min_count and has_field == n and not shadow_leak and not photos_leak and terrace_source_ok,
            f"count={n} expected>{min_count} has_field={has_field}/{n} shadow_leak={shadow_leak} photos_leak={photos_leak}",
        )

    # Nantes specific mix: >=80 confirmed true AND >=500 confirmed false
    r = await client.get(f"{BASE}/terraces", params={"city": "Nantes"})
    if r.status_code == 200:
        ts = _extract_terraces(r.json()) or r.json().get("terraces", [])
        n_true = sum(1 for t in ts if t.get("has_terrace_confirmed") is True)
        n_false = sum(1 for t in ts if t.get("has_terrace_confirmed") is False)
        rec(
            "terraces.nantes.mix_confirmed",
            n_true >= 80 and n_false >= 500,
            f"confirmed_true={n_true} (>=80) confirmed_false={n_false} (>=500) total={len(ts)}",
        )
    else:
        rec("terraces.nantes.mix_confirmed", False, f"status={r.status_code}")


async def test_search(client: httpx.AsyncClient) -> None:
    # 1. search lieu&city=Nantes -> Le Lieu Unique MUST be in top 8 (ideally position 1)
    r = await client.get(f"{BASE}/terraces/search", params={"q": "lieu", "city": "Nantes"})
    if r.status_code == 200:
        res = _extract_terraces(r.json())
        names_top = [t.get("name") for t in res[:8]]
        pos = next((i for i, t in enumerate(res) if "Lieu Unique" in (t.get("name") or "")), -1)
        lieu = res[pos] if pos >= 0 else None
        if lieu and pos < 8:
            ok = (
                lieu.get("has_terrace_confirmed") is True
                and "shadow_map" not in lieu
                and "community_photos" not in lieu
            )
            rec(
                "search.lieu_unique_nantes",
                ok,
                f"position={pos+1}/{len(res)} top8={names_top} has_conf={lieu.get('has_terrace_confirmed')} shadow={lieu.get('shadow_analyzed')} sun_status={lieu.get('sun_status')}",
            )
        else:
            rec(
                "search.lieu_unique_nantes",
                False,
                f"position={pos+1 if pos >= 0 else 'not found'}/{len(res)} top8={names_top}",
            )
    else:
        rec("search.lieu_unique_nantes", False, f"status={r.status_code}")

    # 2. search cigale -> La Cigale + no leak
    r = await client.get(f"{BASE}/terraces/search", params={"q": "cigale"})
    if r.status_code == 200:
        res = _extract_terraces(r.json())
        leak = any("shadow_map" in t or "community_photos" in t for t in res)
        has_field = all("has_terrace_confirmed" in t and isinstance(t["has_terrace_confirmed"], bool) for t in res)
        rec(
            "search.cigale_no_leak",
            len(res) >= 1 and not leak and has_field,
            f"count={len(res)} leak={leak} has_field_all={has_field}",
        )
    else:
        rec("search.cigale_no_leak", False, f"status={r.status_code}")


async def test_terrace_detail(client: httpx.AsyncClient) -> None:
    r = await client.get(f"{BASE}/terraces/{ID_LIEU_UNIQUE}")
    if r.status_code != 200:
        rec("detail.lieu_unique", False, f"status={r.status_code}")
        return
    t = r.json()
    ok = (
        t.get("id") == ID_LIEU_UNIQUE
        and isinstance(t.get("has_terrace_confirmed"), bool)
        and "shadow_map" not in t
        and "sun_schedule_today" in t
        and "hourly_forecast" in t
    )
    rec(
        "detail.lieu_unique",
        ok,
        f"has_conf={t.get('has_terrace_confirmed')} shadow_map_absent={'shadow_map' not in t} schedule={'sun_schedule_today' in t} hourly_n={len(t.get('hourly_forecast') or [])}",
    )

    # Unknown id
    r = await client.get(f"{BASE}/terraces/nonexistent-id-zzz")
    rec("detail.nonexistent_404", r.status_code == 404, f"status={r.status_code}")


async def test_favorites(client: httpx.AsyncClient) -> None:
    r = await client.post(
        f"{BASE}/terraces/favorites",
        json={"ids": [ID_LIEU_UNIQUE, ID_LA_CIGALE]},
    )
    if r.status_code != 200:
        rec("favorites.two_ids", False, f"status={r.status_code} body={r.text[:200]}")
        return
    d = r.json()
    ts = d.get("terraces", [])
    count = d.get("count", -1)
    if count == 2 and len(ts) == 2:
        order_ok = ts[0]["id"] == ID_LIEU_UNIQUE and ts[1]["id"] == ID_LA_CIGALE
        has_conf = all("has_terrace_confirmed" in t and isinstance(t["has_terrace_confirmed"], bool) for t in ts)
        shadow_ok = all(t.get("shadow_analyzed") is True for t in ts)
        leak = any("shadow_map" in t or "community_photos" in t for t in ts)
        rec(
            "favorites.two_ids",
            order_ok and has_conf and shadow_ok and not leak,
            f"order={order_ok} has_conf_all={has_conf} shadow={shadow_ok} leak={leak}",
        )
    else:
        rec("favorites.two_ids", False, f"count={count} len={len(ts)}")


async def test_next_sunny_and_sun(client: httpx.AsyncClient) -> None:
    r = await client.get(f"{BASE}/next-sunny", params={"city": "Nantes"})
    if r.status_code == 200:
        d = r.json()
        rec(
            "next_sunny.nantes_found",
            d.get("found") is True,
            f"found={d.get('found')} terrace={d.get('terrace_name')} time={d.get('first_sunny_time')}",
        )
    else:
        rec("next_sunny.nantes_found", False, f"status={r.status_code}")

    r = await client.get(f"{BASE}/sun-position", params={"lat": 47.2184, "lng": -1.5536})
    rec("sun_position.200", r.status_code == 200, f"status={r.status_code}")

    r = await client.post(
        f"{BASE}/sun-check",
        json={"lat": 47.2184, "lng": -1.5536, "orientation_degrees": 180},
    )
    rec("sun_check.200", r.status_code == 200, f"status={r.status_code}")

    r = await client.get(f"{BASE}/weather/Nantes")
    if r.status_code == 200:
        rec("weather.nantes", True, "200 OK")
    elif r.status_code == 502:
        rec("weather.nantes", True, "Minor: 502 Open-Meteo rate-limit (accepted)")
    else:
        rec("weather.nantes", False, f"status={r.status_code}")


async def test_crowdsourcing_auto_mask(client: httpx.AsyncClient, mdb) -> None:
    """Critical: 3 no_terrace reports on a fresh terrace -> terrace_source='community_hidden' and
    terrace disappears from /terraces?city=Nantes listing."""
    # 1. Submit a temp terrace in Nantes
    r = await client.post(
        f"{BASE}/terraces/submit",
        json={
            "name": "AutoMask Smoke Terrasse",
            "type": "bar",
            "orientation_label": "sud",
            "lat": 47.2184,
            "lng": -1.5536,
            "city": "Nantes",
        },
    )
    new_id = r.json().get("id") if r.status_code == 200 else None
    if not new_id:
        rec("automask.submit", False, f"status={r.status_code} body={r.text[:200]}")
        return
    rec("automask.submit", True, f"new_id={new_id}")

    # Verify default has_terrace_confirmed=True on submitted doc
    doc = await mdb.terraces.find_one({"id": new_id})
    rec(
        "automask.submit_default_confirmed_true",
        doc and doc.get("has_terrace_confirmed") is True and doc.get("terrace_source") == "user_submission",
        f"has_conf={doc.get('has_terrace_confirmed') if doc else None} source={doc.get('terrace_source') if doc else None}",
    )

    # 2. Verify it is in /terraces?city=Nantes
    r = await client.get(f"{BASE}/terraces", params={"city": "Nantes"})
    present = False
    if r.status_code == 200:
        ts = _extract_terraces(r.json()) or r.json().get("terraces", [])
        present = any(t.get("id") == new_id for t in ts)
    rec("automask.initially_visible", present, f"listed_before_reports={present}")

    # 3. Post 3 no_terrace reports
    for i in range(3):
        r = await client.post(
            f"{BASE}/terraces/{new_id}/report",
            json={"type": "no_terrace"},
        )
        if r.status_code != 200:
            rec(f"automask.report_no_terrace_{i+1}", False, f"status={r.status_code}")
            break
    else:
        last = r.json()
        rec(
            "automask.report_no_terrace_3x",
            last.get("hidden") is True and last.get("reports", {}).get("no_terrace", 0) >= 3,
            f"hidden={last.get('hidden')} counters={last.get('reports')}",
        )

    # 4. Verify mongo doc has terrace_source='community_hidden' AND has_terrace_confirmed=False
    doc = await mdb.terraces.find_one({"id": new_id})
    rec(
        "automask.mongo_hidden_flags",
        doc
        and doc.get("terrace_source") == "community_hidden"
        and doc.get("has_terrace_confirmed") is False,
        f"source={doc.get('terrace_source') if doc else None} has_conf={doc.get('has_terrace_confirmed') if doc else None}",
    )

    # 5. Verify it is NO LONGER in /terraces?city=Nantes (excluded by terrace_source)
    r = await client.get(f"{BASE}/terraces", params={"city": "Nantes"})
    still = True
    if r.status_code == 200:
        ts = _extract_terraces(r.json()) or r.json().get("terraces", [])
        still = any(t.get("id") == new_id for t in ts)
    rec("automask.excluded_after_3_reports", not still, f"still_listed={still}")

    # 6. Cleanup: remove temp terrace + its reports
    await mdb.reports.delete_many({"terrace_id": new_id})
    await mdb.terraces.delete_one({"id": new_id})
    rec("automask.cleanup", True, "temp terrace + reports deleted")


async def test_crowdsourcing_remaining(client: httpx.AsyncClient, mdb) -> None:
    """POST /report(confirmed), /photo, /pro/contact all 200 + cleanup."""
    # report confirmed on La Cigale
    r = await client.post(f"{BASE}/terraces/{ID_LA_CIGALE}/report", json={"type": "confirmed"})
    rec(
        "crowd.report_confirmed",
        r.status_code == 200 and r.json().get("ok") is True,
        f"status={r.status_code}",
    )

    # photo upload
    r = await client.post(
        f"{BASE}/terraces/{ID_LA_CIGALE}/photo",
        json={"image_base64": TINY_PNG_B64, "caption": "pivot_smoke"},
    )
    photo_id = r.json().get("photo_id") if r.status_code == 200 else None
    rec(
        "crowd.photo_upload",
        r.status_code == 200 and bool(photo_id),
        f"status={r.status_code} photo_id={photo_id}",
    )

    # pro contact
    r = await client.post(
        f"{BASE}/pro/contact",
        json={
            "establishment_name": "Bar PivotSmoke",
            "email": "pivot.smoke@example.fr",
            "city": "Nantes",
            "message": "pivot smoke",
        },
    )
    lead_id = r.json().get("id") if r.status_code == 200 else None
    rec(
        "crowd.pro_contact",
        r.status_code == 200 and bool(lead_id),
        f"status={r.status_code} lead_id={lead_id}",
    )

    # Cleanup
    try:
        if lead_id:
            await mdb.pro_leads.delete_one({"id": lead_id})
        await mdb.reports.delete_many({"terrace_id": ID_LA_CIGALE, "type": "confirmed"})
        await mdb.terraces.update_one(
            {"id": ID_LA_CIGALE},
            {
                "$pull": {"community_photos": {"caption": "pivot_smoke"}},
                "$set": {"reports.confirmed": 0},
            },
        )
        rec("crowd.cleanup", True, "pro_leads + reports + community_photos reset ok")
    except Exception as e:
        rec("crowd.cleanup", False, f"cleanup error: {e}")


async def test_global_strip_contract(client: httpx.AsyncClient) -> None:
    """shadow_map never exposed; community_photos absent from /terraces and /terraces/search."""
    for city in ["Nantes", "Paris", "Lyon"]:
        r = await client.get(f"{BASE}/terraces", params={"city": city})
        if r.status_code == 200:
            ts = _extract_terraces(r.json()) or r.json().get("terraces", [])
            sleak = sum(1 for t in ts if "shadow_map" in t)
            cleak = sum(1 for t in ts if "community_photos" in t)
            rec(
                f"contract.strip.terraces.{city.lower()}",
                sleak == 0 and cleak == 0,
                f"n={len(ts)} shadow_leak={sleak} community_photos_leak={cleak}",
            )
        else:
            rec(f"contract.strip.terraces.{city.lower()}", False, f"status={r.status_code}")

    for q in ["cafe", "bar", "lieu"]:
        r = await client.get(f"{BASE}/terraces/search", params={"q": q})
        if r.status_code == 200:
            res = _extract_terraces(r.json())
            sleak = sum(1 for t in res if "shadow_map" in t)
            cleak = sum(1 for t in res if "community_photos" in t)
            rec(
                f"contract.strip.search.{q}",
                sleak == 0 and cleak == 0,
                f"n={len(res)} shadow_leak={sleak} community_photos_leak={cleak}",
            )

    # /terraces/{id}: shadow_map must be absent
    r = await client.get(f"{BASE}/terraces/{ID_LIEU_UNIQUE}")
    if r.status_code == 200:
        t = r.json()
        rec(
            "contract.strip.detail.lieu_unique",
            "shadow_map" not in t,
            f"shadow_map_key_present={'shadow_map' in t}",
        )


async def main() -> int:
    print(f"Target BASE={BASE}")
    mclient = AsyncIOMotorClient(MONGO_URL)
    mdb = mclient[DB_NAME]
    timeout = httpx.Timeout(60.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        print("\n=== /api/cities ===")
        await test_cities(client)

        print("\n=== /api/terraces pivot counts + has_terrace_confirmed ===")
        await test_terraces_counts_pivot(client)

        print("\n=== /api/terraces/search ===")
        await test_search(client)

        print("\n=== /api/terraces/{id} ===")
        await test_terrace_detail(client)

        print("\n=== /api/terraces/favorites ===")
        await test_favorites(client)

        print("\n=== /api/next-sunny + /sun-position + /sun-check + /weather ===")
        await test_next_sunny_and_sun(client)

        print("\n=== CRITICAL: auto-masking crowdsourcing ===")
        await test_crowdsourcing_auto_mask(client, mdb)

        print("\n=== Crowdsourcing (report/photo/pro-contact) + cleanup ===")
        await test_crowdsourcing_remaining(client, mdb)

        print("\n=== Contract strip heavy fields (shadow_map / community_photos) ===")
        await test_global_strip_contract(client)

    passed = sum(1 for _, ok, _ in results if ok)
    failed = sum(1 for _, ok, _ in results if not ok)
    print(f"\n=== SUMMARY: {passed}/{len(results)} PASS, {failed} FAIL ===")
    for name, ok, detail in results:
        if not ok:
            print(f"  [FAIL] {name} :: {detail}")
    mclient.close()
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
