"""
Soleia - Shadow Engine (MVP OSM-based 3D ray casting)
=====================================================

Computes whether a terrace is in the shadow of surrounding buildings,
using OpenStreetMap building footprints + heights.

Pipeline:
 1. Overpass API fetches buildings within ~250m of the terrace.
 2. Each building polygon is extruded to its estimated height (OSM tags
    `height`, `building:levels`, or default by building type).
 3. For a given time, pysolar gives the sun azimuth and altitude.
 4. We cast a 2D ray from the terrace in the sun azimuth direction and
    find the nearest building polygon intersection. At that distance d,
    the ray's height is `seat + d * tan(altitude)`. If the building top
    is higher → the terrace is in shadow at that time.

This is a strong improvement over pure orientation-based heuristics:
 - Correctly handles narrow streets and tall neighbouring buildings.
 - Agnostic to the terrace orientation (a south-facing terrace in a
   deep alley can still be shaded all day).

Caveats:
 - OSM height data is incomplete; we fall back to defaults per building
   type (which is accurate enough in dense European city centres).
 - We sample one ray per timepoint (no diffuse light / reflections).
 - Self-shadowing of the terrace's own building is explicitly skipped
   (ignored if distance < 1 m).
"""

from __future__ import annotations

import math
import logging
from datetime import datetime, timedelta, timezone, date
from zoneinfo import ZoneInfo
from typing import Dict, List, Tuple, Optional

import requests
from shapely.geometry import Polygon, Point, LineString
from pysolar.solar import get_altitude, get_azimuth

logger = logging.getLogger(__name__)

# ---- Overpass ---------------------------------------------------------------
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]

# ---- Height heuristics ------------------------------------------------------
DEFAULT_LEVEL_HEIGHT = 3.0  # meters per floor (OSM convention ≈ 2.5-3m)
DEFAULT_HEIGHTS = {
    "church": 30.0,
    "cathedral": 45.0,
    "tower": 30.0,
    "chapel": 12.0,
    "castle": 20.0,
    "house": 7.0,
    "detached": 7.0,
    "bungalow": 5.0,
    "apartments": 16.0,
    "residential": 14.0,
    "dormitory": 14.0,
    "hotel": 20.0,
    "school": 10.0,
    "university": 14.0,
    "hospital": 14.0,
    "office": 18.0,
    "retail": 7.0,
    "commercial": 10.0,
    "industrial": 9.0,
    "warehouse": 9.0,
    "parking": 6.0,
    "garage": 3.0,
    "shed": 3.0,
    "terrace": 10.0,
    "yes": 12.0,  # default when only building=yes
}

SEATED_HEIGHT_M = 1.5  # height of terrace occupant (chair + torso)
RAY_MAX_DISTANCE_M = 250.0
MIN_BUILDING_AREA_M2 = 4.0

# ---- Helpers ---------------------------------------------------------------


def parse_building_height(tags: dict) -> float:
    """Estimate building height in meters from OSM tags."""
    for key in ("height", "building:height"):
        raw = tags.get(key)
        if raw:
            try:
                # Accept "15", "15m", "15 m", "15,5"
                cleaned = raw.replace(",", ".").replace("m", "").strip()
                return max(3.0, float(cleaned))
            except (ValueError, AttributeError):
                pass
    lvl = tags.get("building:levels") or tags.get("levels")
    if lvl:
        try:
            return max(3.0, float(str(lvl).replace(",", ".")) * DEFAULT_LEVEL_HEIGHT)
        except (ValueError, AttributeError):
            pass
    btype = tags.get("building", "yes")
    return DEFAULT_HEIGHTS.get(btype, DEFAULT_HEIGHTS["yes"])


def fetch_osm_buildings(
    lat: float, lng: float, radius_m: float = 250.0, timeout_s: int = 60
) -> List[Tuple[List[Tuple[float, float]], float]]:
    """Return list of (coords_latlng, height_m) for buildings around (lat, lng)."""
    query = f"""
    [out:json][timeout:50];
    (
      way["building"](around:{int(radius_m)},{lat},{lng});
    );
    out body;
    >;
    out skel qt;
    """
    last_err: Optional[Exception] = None
    headers = {
        "User-Agent": "Soleia/1.0 (terrace sunshine analyser; contact@soleia.app)",
        "Accept": "application/json",
    }
    import time

    # Retry up to 4 times, backoff 2/5/15/45s, cycling through mirrors.
    backoffs = [2, 5, 15, 45]
    for attempt, backoff in enumerate(backoffs):
        for url in OVERPASS_MIRRORS:
            try:
                resp = requests.post(
                    url,
                    data=query.encode("utf-8"),
                    headers=headers,
                    timeout=timeout_s,
                )
                if resp.status_code == 429:
                    last_err = Exception(f"429 Too Many Requests from {url}")
                    logger.warning("Overpass 429, will back off %ss", backoff)
                    continue
                resp.raise_for_status()
                data = resp.json()
                return_data = data
                break
            except Exception as e:
                last_err = e
                logger.warning("Overpass mirror failed (%s): %s", url, e)
                continue
        else:
            if attempt < len(backoffs) - 1:
                time.sleep(backoff)
                continue
            raise RuntimeError(f"All Overpass mirrors failed: {last_err}")
        break  # success path
    data = return_data

    nodes = {
        el["id"]: (el["lat"], el["lon"])
        for el in data.get("elements", [])
        if el["type"] == "node"
    }

    buildings: List[Tuple[List[Tuple[float, float]], float]] = []
    for el in data.get("elements", []):
        if el["type"] != "way":
            continue
        tags = el.get("tags", {})
        if "building" not in tags:
            continue
        coords = [nodes[nid] for nid in el.get("nodes", []) if nid in nodes]
        if len(coords) < 3:
            continue
        height = parse_building_height(tags)
        buildings.append((coords, height))
    return buildings


def fetch_osm_buildings_bbox(
    lat_min: float, lng_min: float, lat_max: float, lng_max: float, timeout_s: int = 60
) -> List[Tuple[List[Tuple[float, float]], float]]:
    """Return list of (coords_latlng, height_m) for all buildings in a bbox."""
    query = f"""
    [out:json][timeout:50];
    (
      way["building"]({lat_min},{lng_min},{lat_max},{lng_max});
    );
    out body;
    >;
    out skel qt;
    """
    headers = {
        "User-Agent": "Soleia/1.0 (shadow overlay; contact@soleia.app)",
        "Accept": "application/json",
    }
    import time
    last_err = None
    return_data = None
    for attempt, backoff in enumerate([2, 5, 15]):
        for url in OVERPASS_MIRRORS:
            try:
                resp = requests.post(
                    url, data=query.encode("utf-8"), headers=headers, timeout=timeout_s
                )
                if resp.status_code == 429:
                    last_err = Exception(f"429 from {url}")
                    continue
                resp.raise_for_status()
                return_data = resp.json()
                break
            except Exception as e:
                last_err = e
                continue
        if return_data is not None:
            break
        if attempt < 2:
            time.sleep(backoff)
    if return_data is None:
        raise RuntimeError(f"All Overpass mirrors failed: {last_err}")

    nodes = {
        el["id"]: (el["lat"], el["lon"])
        for el in return_data.get("elements", [])
        if el["type"] == "node"
    }
    buildings: List[Tuple[List[Tuple[float, float]], float]] = []
    for el in return_data.get("elements", []):
        if el["type"] != "way":
            continue
        tags = el.get("tags", {})
        if "building" not in tags:
            continue
        coords = [nodes[nid] for nid in el.get("nodes", []) if nid in nodes]
        if len(coords) < 3:
            continue
        height = parse_building_height(tags)
        buildings.append((coords, height))
    return buildings


def enu_to_latlng(e: float, n: float, ref_lat: float, ref_lng: float) -> Tuple[float, float]:
    """Inverse of latlng_to_enu."""
    R = 6371008.8
    lat = ref_lat + math.degrees(n / R)
    lng = ref_lng + math.degrees(e / (R * math.cos(math.radians(ref_lat))))
    return lat, lng


def project_shadow_polygons_latlng(
    buildings: List[Tuple[List[Tuple[float, float]], float]],
    sun_azimuth_deg: float,
    sun_altitude_deg: float,
    ref_lat: float,
    ref_lng: float,
    max_polys: int = 120,
) -> List[List[Tuple[float, float]]]:
    """
    Project each building's rooftop shadow on the ground as a latlng polygon.

    The shadow of a vertical prism on flat ground = convex hull of (footprint ∪
    footprint translated by -(shadow_length * sun_ground_direction)).
    Returns a list of polygons, each as [(lat,lng), ...].
    """
    if sun_altitude_deg <= 2.0:
        return []  # sun too low → diffuse / whole world in shadow, not useful

    from shapely.geometry import MultiPoint, Polygon as ShPoly

    # Ground direction of the shadow = opposite of sun direction
    az_rad = math.radians(sun_azimuth_deg % 360)
    dx_sun = math.sin(az_rad)  # east
    dy_sun = math.cos(az_rad)  # north
    # Shadow points OPPOSITE to the sun direction
    dx_shadow = -dx_sun
    dy_shadow = -dy_sun
    tan_el = math.tan(math.radians(sun_altitude_deg))

    # Douglas-Peucker tolerance (en mètres ENU). 3 m = différence imperceptible
    # à zoom 14-16, mais réduit drastiquement le nombre de vertices pour le GPU
    # client (Mapbox iOS ShapeSource sature au-delà de ~1500 vertices total).
    SIMPLIFY_TOL_M = 3.0

    out: List[List[Tuple[float, float]]] = []
    # Sort buildings by height desc → prioritize taller buildings that cast longer shadows
    sorted_b = sorted(buildings, key=lambda b: -b[1])
    for coords, h in sorted_b[:max_polys]:
        shadow_len = h / tan_el if tan_el > 0 else 0
        # Skip very short shadows (< 2m) to reduce noise
        if shadow_len < 2.0:
            continue
        # Project footprint to local ENU
        enu_pts = [latlng_to_enu(la, ln, ref_lat, ref_lng) for la, ln in coords]
        # Translated copy
        tx = dx_shadow * shadow_len
        ty = dy_shadow * shadow_len
        translated = [(p[0] + tx, p[1] + ty) for p in enu_pts]
        # Union via convex hull of both point sets = shadow polygon
        try:
            hull = MultiPoint(enu_pts + translated).convex_hull
            if hull.geom_type != "Polygon":
                continue
            # Douglas-Peucker simplification — réduit ~11-15 points → 4-7 sans
            # perte visible. preserve_topology=True évite les self-intersections.
            simplified = hull.simplify(SIMPLIFY_TOL_M, preserve_topology=True)
            if simplified.geom_type != "Polygon" or simplified.is_empty:
                simplified = hull
            latlng = [enu_to_latlng(e, n, ref_lat, ref_lng) for e, n in simplified.exterior.coords]
            out.append(latlng)
        except Exception:
            continue
    return out


def compute_shadow_overlay(
    lat_min: float,
    lng_min: float,
    lat_max: float,
    lng_max: float,
    at_time_utc: datetime,
) -> dict:
    """
    Compute shadow polygons for a bbox at a given UTC time.
    Returns {"polygons": [[[lat,lng],...],...], "sun": {"az":..., "el":...},
             "building_count": N}.
    """
    ref_lat = (lat_min + lat_max) / 2.0
    ref_lng = (lng_min + lng_max) / 2.0
    el = float(get_altitude(ref_lat, ref_lng, at_time_utc))
    az = float(get_azimuth(ref_lat, ref_lng, at_time_utc))

    if el <= 2.0:
        return {"polygons": [], "sun": {"az": az, "el": el}, "building_count": 0}

    try:
        buildings = fetch_osm_buildings_bbox(lat_min, lng_min, lat_max, lng_max)
    except Exception as exc:
        logger.warning("Overpass bbox fetch failed: %s", exc)
        return {"polygons": [], "sun": {"az": az, "el": el}, "building_count": 0}

    polygons = project_shadow_polygons_latlng(buildings, az, el, ref_lat, ref_lng, max_polys=300)
    return {
        "polygons": polygons,
        "sun": {"az": az, "el": el},
        "building_count": len(buildings),
    }


def latlng_to_enu(
    lat: float, lng: float, ref_lat: float, ref_lng: float
) -> Tuple[float, float]:
    """Equirectangular projection to local ENU meters. OK within a few hundred meters."""
    R = 6371008.8
    dlat = math.radians(lat - ref_lat)
    dlng = math.radians(lng - ref_lng)
    e = dlng * R * math.cos(math.radians(ref_lat))
    n = dlat * R
    return e, n


def buildings_to_polygons(
    buildings, ref_lat: float, ref_lng: float
) -> List[Tuple[Polygon, float]]:
    out: List[Tuple[Polygon, float]] = []
    for coords, h in buildings:
        pts = [latlng_to_enu(la, ln, ref_lat, ref_lng) for la, ln in coords]
        if len(pts) < 3:
            continue
        try:
            poly = Polygon(pts)
            if not poly.is_valid:
                poly = poly.buffer(0)
            if poly.is_empty or poly.area < MIN_BUILDING_AREA_M2:
                continue
            out.append((poly, float(h)))
        except Exception:
            continue
    return out


def is_shadow_blocked(
    sun_azimuth_deg: float,
    sun_altitude_deg: float,
    polys: List[Tuple[Polygon, float]],
    max_distance_m: float = RAY_MAX_DISTANCE_M,
    seat_height_m: float = SEATED_HEIGHT_M,
) -> bool:
    """
    Cast a ray from (0,0,seat) in the sun direction; return True if a
    building top is above the ray at the intersection distance.
    """
    if sun_altitude_deg <= 1.5:
        # Sun too low — handled elsewhere (considered "no direct sun" rather
        # than shadow from buildings). We return False here; callers should
        # first check altitude > horizon.
        return False

    az = math.radians(sun_azimuth_deg % 360)
    # ENU: east = sin(az), north = cos(az) (0° = North convention of pysolar)
    dx = math.sin(az)
    dy = math.cos(az)
    tan_el = math.tan(math.radians(sun_altitude_deg))

    origin = Point(0.0, 0.0)
    end = (dx * max_distance_m, dy * max_distance_m)
    ray = LineString([(0.0, 0.0), end])

    closest_hit = None  # (distance, building_height)
    for poly, h in polys:
        if not ray.intersects(poly):
            continue
        inter = ray.intersection(poly)
        if inter.is_empty:
            continue
        # Collect candidate geometry points and pick the nearest to origin
        candidates: List[Point] = []
        if inter.geom_type == "Point":
            candidates.append(inter)
        elif inter.geom_type == "MultiPoint":
            candidates.extend(inter.geoms)
        elif inter.geom_type == "LineString":
            candidates.extend([Point(inter.coords[0]), Point(inter.coords[-1])])
        elif inter.geom_type == "MultiLineString":
            for seg in inter.geoms:
                candidates.extend([Point(seg.coords[0]), Point(seg.coords[-1])])
        else:
            # GeometryCollection etc.
            try:
                candidates.extend([Point(c) for c in inter.coords])
            except Exception:
                continue
        for pt in candidates:
            d = origin.distance(pt)
            if d < 1.0:
                continue  # ignore self-building / noise
            if closest_hit is None or d < closest_hit[0]:
                closest_hit = (d, h)

    if closest_hit is None:
        return False

    d, building_h = closest_hit
    ray_height_at_d = seat_height_m + d * tan_el
    return building_h > ray_height_at_d


# ---- Main API --------------------------------------------------------------


def compute_shadow_map(
    lat: float,
    lng: float,
    tz_name: str = "Europe/Paris",
    sample_date: Optional[date] = None,
    step_minutes: int = 30,
    radius_m: float = 250.0,
) -> Tuple[Dict[str, bool], int]:
    """
    For a terrace at (lat, lng), compute a minute-of-day → blocked map
    between 06:00 and 22:00 in local time. Returns ({'06:00': True, ...},
    number_of_buildings_considered).

    A value is True when a building blocks direct sun for that timepoint.
    A value is also True if the sun is below horizon (no sun).
    """
    raw = fetch_osm_buildings(lat, lng, radius_m=radius_m)
    polys = buildings_to_polygons(raw, lat, lng)

    tz = ZoneInfo(tz_name)
    if sample_date is None:
        sample_date = datetime.now(tz).date()

    shadow_map: Dict[str, bool] = {}
    m = 6 * 60
    end = 22 * 60
    while m <= end:
        hh, mm = divmod(m, 60)
        dt_local = datetime(
            sample_date.year,
            sample_date.month,
            sample_date.day,
            hh,
            mm,
            tzinfo=tz,
        )
        dt_utc = dt_local.astimezone(timezone.utc)
        el = float(get_altitude(lat, lng, dt_utc))
        if el <= 1.5:
            shadow_map[f"{hh:02d}:{mm:02d}"] = True  # "no sun" counts as blocked
        else:
            az = float(get_azimuth(lat, lng, dt_utc))
            shadow_map[f"{hh:02d}:{mm:02d}"] = is_shadow_blocked(az, el, polys)
        m += step_minutes

    return shadow_map, len(polys)


def lookup_shadow_blocked(
    shadow_map: Dict[str, bool], target_time_local: datetime, step_minutes: int = 30
) -> Optional[bool]:
    """Lookup in a pre-computed shadow map rounded to step."""
    if not shadow_map:
        return None
    total = target_time_local.hour * 60 + target_time_local.minute
    snapped = (total // step_minutes) * step_minutes
    hh, mm = divmod(snapped, 60)
    key = f"{hh:02d}:{mm:02d}"
    if key in shadow_map:
        return shadow_map[key]
    # fallback: nearest key
    keys = sorted(shadow_map.keys())
    if not keys:
        return None
    best = min(keys, key=lambda k: abs(int(k[:2]) * 60 + int(k[3:]) - total))
    return shadow_map[best]


if __name__ == "__main__":
    # Simple smoke test on Le Lieu Unique (Nantes)
    lat, lng = 47.2126, -1.5458
    print(f"Testing on Nantes ({lat}, {lng})...")
    smap, nb = compute_shadow_map(lat, lng)
    for k, v in smap.items():
        flag = "🌑" if v else "☀️"
        print(f"  {k}  {flag}")
    print(f"Total buildings sampled: {nb}")
