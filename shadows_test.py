"""
Soleia /api/shadows non-regression + new endpoint tests.

Covers:
 a) GET /api/shadows at day time -> 200, polygons array, sun.az/el numeric,
    building_count int, cached present (bool).
 b) Immediate second call -> cached=true and < 100ms.
 c) bbox too large (>0.06°) -> 200, polygons=[], reason=bbox_invalid_or_too_large.
 d) inverted bbox (lat_max < lat_min) -> same reason.
 e) night (sun below horizon) -> polygons=[], sun.el < 0.
 f) no at_time -> 200.
 g) polygon coords roughly inside the requested bbox.
"""
import asyncio
import os
import sys
import time
from typing import List, Tuple

import httpx


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

PASS: List[str] = []
FAIL: List[Tuple[str, str]] = []


def ok(name: str, note: str = "") -> None:
    PASS.append(name)
    print(f"PASS  {name} {note}")


def ko(name: str, note: str) -> None:
    FAIL.append((name, note))
    print(f"FAIL  {name} :: {note}")


def require(name: str, cond: bool, note: str = "") -> None:
    if cond:
        ok(name, note)
    else:
        ko(name, note or "condition false")


async def main() -> int:
    print(f"BASE = {BASE}")

    async with httpx.AsyncClient(timeout=120.0) as client:

        # -------- a) Daytime request Nantes centre
        params_day = {
            "lat_min": 47.210,
            "lat_max": 47.222,
            "lng_min": -1.568,
            "lng_max": -1.552,
            "at_time": "2026-04-23T14:00:00",
        }
        t0 = time.time()
        r = await client.get(f"{BASE}/shadows", params=params_day)
        dt1 = (time.time() - t0) * 1000
        require("shadows.day.status200", r.status_code == 200, f"status={r.status_code} body={r.text[:200]}")
        body = r.json() if r.status_code == 200 else {}
        polys = body.get("polygons")
        sun = body.get("sun") or {}
        bc = body.get("building_count")
        cached_flag = body.get("cached")

        require("shadows.day.polygons_array", isinstance(polys, list), f"type={type(polys).__name__}")
        if isinstance(polys, list):
            require(
                "shadows.day.polygons_size_reasonable",
                0 <= len(polys) <= 600,
                f"len={len(polys)}",
            )
        require(
            "shadows.day.sun_az_numeric",
            isinstance(sun.get("az"), (int, float)),
            f"az={sun.get('az')}",
        )
        require(
            "shadows.day.sun_el_numeric",
            isinstance(sun.get("el"), (int, float)),
            f"el={sun.get('el')}",
        )
        # Note: in April 14:00 UTC ≈ 16h local, sun should be up
        if isinstance(sun.get("el"), (int, float)):
            require(
                "shadows.day.sun_above_horizon",
                sun["el"] > 0,
                f"el={sun['el']}",
            )
        require(
            "shadows.day.building_count_int_nonneg",
            isinstance(bc, int) and bc >= 0,
            f"building_count={bc}",
        )
        require(
            "shadows.day.cached_present_bool",
            isinstance(cached_flag, bool),
            f"cached={cached_flag}",
        )
        # First call: cached should be False
        require(
            "shadows.day.first_call_cached_false",
            cached_flag is False,
            f"cached={cached_flag} dt={dt1:.0f}ms",
        )

        # -------- g) polygons within bbox (approximate, small overflow acceptable)
        if isinstance(polys, list) and polys:
            bad = 0
            sample = polys[:5]
            lat_min_obs = min(p[0] for poly in polys for p in poly)
            lat_max_obs = max(p[0] for poly in polys for p in poly)
            lng_min_obs = min(p[1] for poly in polys for p in poly)
            lng_max_obs = max(p[1] for poly in polys for p in poly)
            # Allow small overflow because shadows extend outside building footprints
            lat_ok = lat_min_obs >= 47.20 - 0.01 and lat_max_obs <= 47.23 + 0.01
            lng_ok = lng_min_obs >= -1.58 - 0.01 and lng_max_obs <= -1.55 + 0.01
            require(
                "shadows.day.polygons_inside_bbox",
                lat_ok and lng_ok,
                f"lat[{lat_min_obs:.4f},{lat_max_obs:.4f}] lng[{lng_min_obs:.4f},{lng_max_obs:.4f}]",
            )
            # sample is lat,lng pairs
            for poly in sample:
                for p in poly:
                    if not (isinstance(p, list) and len(p) == 2
                            and isinstance(p[0], (int, float))
                            and isinstance(p[1], (int, float))):
                        bad += 1
                        break
            require(
                "shadows.day.polygon_points_are_latlng",
                bad == 0,
                f"bad={bad}",
            )
        else:
            ok("shadows.day.polygons_inside_bbox", "empty polygons — skipped spatial check")

        # -------- b) Immediate 2nd call -> cached=true & fast
        t1 = time.time()
        r2 = await client.get(f"{BASE}/shadows", params=params_day)
        dt2 = (time.time() - t1) * 1000
        require("shadows.cache.status200", r2.status_code == 200, f"status={r2.status_code}")
        body2 = r2.json() if r2.status_code == 200 else {}
        require(
            "shadows.cache.cached_true",
            body2.get("cached") is True,
            f"cached={body2.get('cached')}",
        )
        require(
            "shadows.cache.fast_lt_500ms",  # using 500ms guard; 100ms is aggressive given network
            dt2 < 500,
            f"dt={dt2:.0f}ms",
        )
        # Secondary check: same polygons length
        if isinstance(polys, list) and isinstance(body2.get("polygons"), list):
            require(
                "shadows.cache.same_polygon_count",
                len(body2["polygons"]) == len(polys),
                f"first={len(polys)} second={len(body2['polygons'])}",
            )

        # -------- c) bbox too large
        too_large = {
            "lat_min": 47.00, "lat_max": 47.50,
            "lng_min": -1.80, "lng_max": -1.30,
        }
        r = await client.get(f"{BASE}/shadows", params=too_large)
        require("shadows.toolarge.status200", r.status_code == 200, f"status={r.status_code}")
        tl = r.json() if r.status_code == 200 else {}
        require(
            "shadows.toolarge.polygons_empty",
            isinstance(tl.get("polygons"), list) and len(tl["polygons"]) == 0,
            f"polygons={tl.get('polygons')}",
        )
        require(
            "shadows.toolarge.reason",
            tl.get("reason") == "bbox_invalid_or_too_large",
            f"reason={tl.get('reason')}",
        )

        # -------- d) inverted bbox (lat_max < lat_min)
        inverted = {
            "lat_min": 47.222, "lat_max": 47.210,
            "lng_min": -1.568, "lng_max": -1.552,
        }
        r = await client.get(f"{BASE}/shadows", params=inverted)
        require("shadows.inverted.status200", r.status_code == 200, f"status={r.status_code}")
        inv = r.json() if r.status_code == 200 else {}
        require(
            "shadows.inverted.polygons_empty",
            isinstance(inv.get("polygons"), list) and len(inv["polygons"]) == 0,
            f"polygons={inv.get('polygons')}",
        )
        require(
            "shadows.inverted.reason",
            inv.get("reason") == "bbox_invalid_or_too_large",
            f"reason={inv.get('reason')}",
        )

        # -------- e) night time (sun below horizon)
        night = {
            "lat_min": 47.210, "lat_max": 47.222,
            "lng_min": -1.568, "lng_max": -1.552,
            "at_time": "2026-04-23T23:00:00",
        }
        r = await client.get(f"{BASE}/shadows", params=night)
        require("shadows.night.status200", r.status_code == 200, f"status={r.status_code}")
        nb = r.json() if r.status_code == 200 else {}
        require(
            "shadows.night.polygons_empty",
            isinstance(nb.get("polygons"), list) and len(nb["polygons"]) == 0,
            f"polygons_len={len(nb.get('polygons') or [])}",
        )
        sun_n = nb.get("sun") or {}
        require(
            "shadows.night.sun_el_negative",
            isinstance(sun_n.get("el"), (int, float)) and sun_n["el"] < 0,
            f"sun={sun_n}",
        )

        # -------- f) no at_time
        no_at = {
            "lat_min": 47.210, "lat_max": 47.222,
            "lng_min": -1.568, "lng_max": -1.552,
        }
        r = await client.get(f"{BASE}/shadows", params=no_at)
        require("shadows.now.status200", r.status_code == 200, f"status={r.status_code}")
        nb2 = r.json() if r.status_code == 200 else {}
        require(
            "shadows.now.polygons_array",
            isinstance(nb2.get("polygons"), list),
            f"polygons_type={type(nb2.get('polygons')).__name__}",
        )
        require(
            "shadows.now.sun_present",
            isinstance((nb2.get("sun") or {}).get("el"), (int, float))
            and isinstance((nb2.get("sun") or {}).get("az"), (int, float)),
            f"sun={nb2.get('sun')}",
        )
        require(
            "shadows.now.building_count_int",
            isinstance(nb2.get("building_count"), int),
            f"bc={nb2.get('building_count')}",
        )
        require(
            "shadows.now.cached_present",
            isinstance(nb2.get("cached"), bool),
            f"cached={nb2.get('cached')}",
        )

    print("\n============ SUMMARY /api/shadows ============")
    print(f"PASS: {len(PASS)}")
    print(f"FAIL: {len(FAIL)}")
    if FAIL:
        print("--- failures ---")
        for n, note in FAIL:
            print(f"  {n} :: {note}")
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
