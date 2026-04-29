"""
SunTerrace Backend - FastAPI Server
Calcul solaire en temps réel pour les terrasses françaises.
"""

from fastapi import FastAPI, APIRouter, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime, timedelta, timezone
from math import radians, sin, cos, asin, sqrt
import os
import uuid
import logging
import asyncio
import httpx
import pytz
from pathlib import Path

from sun_engine import (
    compute_sun_status_dynamic,
    compute_sun_schedule_for_day,
    compute_hourly_forecast,
    is_terrace_sunny,
    get_sun_position,
    PARIS_TZ,
)
from seed_data import NANTES_TERRACES, PARIS_TERRACES, CITY_CENTERS, orientation_label
from shadow_engine import lookup_shadow_blocked, compute_shadow_overlay
from auth import auth_router

# Load env BEFORE anything else
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY")

client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]

app = FastAPI(title="SunTerrace API")
api_router = APIRouter(prefix="/api")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("suntterrace")


# =========================
# Models
# =========================
class Terrace(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    lat: float
    lng: float
    orientation_degrees: float
    orientation_label: str
    type: str  # bar, cafe, restaurant, rooftop
    city: str
    arrondissement: Optional[str] = None
    address: str
    google_rating: float
    photo_url: str
    has_cover: bool = False
    capacity_estimate: int = 0
    ai_description: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(pytz.utc))


# =========================
# Helpers
# =========================
def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Distance en km entre deux points GPS."""
    R = 6371.0
    dlat = radians(lat2 - lat1)
    dlng = radians(lng2 - lng1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
    c = 2 * asin(sqrt(a))
    return R * c


def parse_at_time(at_time_str: Optional[str]) -> datetime:
    """
    Parse ISO datetime string, default to now in Europe/Paris.
    Accepte aussi format 'HH:MM' (suppose aujourd'hui).
    """
    now = datetime.now(PARIS_TZ)
    if not at_time_str:
        return now

    try:
        # Essayer ISO format
        dt = datetime.fromisoformat(at_time_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = PARIS_TZ.localize(dt)
        return dt
    except (ValueError, AttributeError):
        pass

    # Essayer format HH:MM ou HH
    try:
        if ":" in at_time_str:
            h, m = at_time_str.split(":")
            return now.replace(hour=int(h), minute=int(m), second=0, microsecond=0)
        else:
            return now.replace(hour=int(at_time_str), minute=0, second=0, microsecond=0)
    except (ValueError, AttributeError):
        return now


def terrace_to_public(doc: dict) -> dict:
    """Nettoie un document MongoDB pour la réponse API (pas de _id)."""
    if not doc:
        return doc
    # Strip heavy fields that shouldn't go over the wire to every client.
    HEAVY_FIELDS = {"_id", "shadow_map", "community_photos"}
    public = {k: v for k, v in doc.items() if k not in HEAVY_FIELDS}
    # Serialize datetime
    if "created_at" in public and isinstance(public["created_at"], datetime):
        public["created_at"] = public["created_at"].isoformat()
    if "shadow_analysis_at" in public and isinstance(
        public["shadow_analysis_at"], datetime
    ):
        public["shadow_analysis_at"] = public["shadow_analysis_at"].isoformat()
    return public


def apply_shadow_override(sun_info: dict, terrace_doc: dict, target_time: datetime) -> dict:
    """
    If the terrace has a pre-computed shadow_map, override `is_sunny`/`status`
    based on the 3D building analysis. Keeps orientation-based logic as the
    fallback.
    """
    smap = terrace_doc.get("shadow_map")
    if not smap:
        return sun_info
    try:
        from zoneinfo import ZoneInfo
        local = target_time.astimezone(ZoneInfo("Europe/Paris"))
        blocked = lookup_shadow_blocked(smap, local)
    except Exception:
        return sun_info
    if blocked is None:
        return sun_info

    # If sun is below horizon, orientation already says "not sunny" — keep it.
    if sun_info.get("sun_altitude", 0) <= 0:
        return sun_info

    new_is_sunny = not blocked
    if new_is_sunny == sun_info.get("is_sunny"):
        # Shadow model agrees with orientation heuristic — just flag it.
        result = dict(sun_info)
        result["shadow_override"] = False
        result["shadow_analyzed"] = True
        return result

    # Shadow model disagrees → it takes precedence (more accurate).
    result = dict(sun_info)
    result["is_sunny"] = new_is_sunny
    result["status"] = "sunny" if new_is_sunny else "shade"
    if not new_is_sunny:
        result["sunny_until"] = None
    result["shadow_override"] = True
    result["shadow_analyzed"] = True
    return result


# =========================
# Routes
# =========================
@api_router.get("/")
async def root():
    return {
        "app": "SunTerrace API",
        "version": "1.0",
        "status": "running",
    }


@api_router.get("/cities")
async def list_cities():
    """Liste des villes supportées."""
    return [
        {"name": name, "lat": coords["lat"], "lng": coords["lng"]}
        for name, coords in CITY_CENTERS.items()
    ]


# List of fast-food brand tokens — exclus aussi côté API pour tolérer d'éventuels
# docs non purgés et les futurs imports. Starbucks n'est PAS dans la liste (gardé).
FAST_FOOD_BRAND_TOKENS = [
    "McDonald",
    "KFC",
    "Burger King",
    "Quick",
    "Five Guys",
    "Subway",
    "Paul",
    "Brioche Dor",
    "Domino",
    "Pizza Hut",
]


def _fast_food_exclusion_filter() -> list:
    """Retourne les conditions Mongo à ajouter dans un `$and` pour exclure les fast-food."""
    import re as _re
    conds = [{"type": {"$ne": "fast_food"}}]
    for token in FAST_FOOD_BRAND_TOKENS:
        conds.append({"name": {"$not": {"$regex": _re.escape(token), "$options": "i"}}})
    return conds


@api_router.get("/terraces")
async def list_terraces(
    city: Optional[str] = Query(None, description="Filtrer par ville (ex: Paris)"),
    lat: Optional[float] = Query(None, description="Latitude utilisateur pour distance"),
    lng: Optional[float] = Query(None, description="Longitude utilisateur pour distance"),
    radius_km: Optional[float] = Query(None, description="Rayon de recherche en km"),
    lat_min: Optional[float] = Query(None, description="Bounding box sud"),
    lat_max: Optional[float] = Query(None, description="Bounding box nord"),
    lng_min: Optional[float] = Query(None, description="Bounding box ouest"),
    lng_max: Optional[float] = Query(None, description="Bounding box est"),
    type: Optional[str] = Query(None, description="Filtrer par type: bar, cafe, restaurant, rooftop"),
    sun_status: Optional[str] = Query(None, description="Filtrer par statut: sunny, soon, shade"),
    min_rating: Optional[float] = Query(None, description="Note minimale Google"),
    at_time: Optional[str] = Query(None, description="ISO datetime ou HH:MM pour calcul soleil à ce moment"),
    limit: int = Query(200, ge=1, le=10000, description="Maximum de résultats (max 10000 pour zoom rue)"),
):
    """
    Liste les terrasses avec calcul solaire dynamique en temps réel.
    Retourne chaque terrasse avec son sun_status calculé pour at_time.
    
    Stratégie d'affichage par type :
      - bar, cafe, rooftop : tous les établissements
      - restaurant : uniquement si has_terrace_confirmed=true OU
                     (google_rating >= 4.0 ET google_ratings_count >= 100)
      - fast_food : jamais affiché
    
    Filtre géographique obligatoire : utiliser lat_min/lat_max/lng_min/lng_max
    pour ne charger que les établissements visibles dans la carte.
    Maximum 2000 résultats par requête (utilisé pour le mode "toutes les villes").
    """
    # Fast-food explicitement demandé → retour vide (jamais affiché)
    if type == "fast_food":
        return {
            "terraces": [],
            "count": 0,
            "at_time": parse_at_time(at_time).isoformat(),
            "query": {"city": city, "type": type, "sun_status": sun_status, "bbox": None},
        }

    and_clauses: list = []
    query: dict = {}
    if city:
        query["city"] = city
    if type and type != "fast_food":
        query["type"] = type
    if min_rating is not None:
        query["google_rating"] = {"$gte": min_rating}

    # Bounding box géographique
    if lat_min is not None and lat_max is not None:
        query["lat"] = {"$gte": lat_min, "$lte": lat_max}
    if lng_min is not None and lng_max is not None:
        query["lng"] = {"$gte": lng_min, "$lte": lng_max}

    # Exclusion : street_view_no_image (pas d'image) + community_hidden (crowdsource masque)
    query["terrace_source"] = {"$nin": ["street_view_no_image", "community_hidden"]}

    # Exclusion fast-food (type + chaînes par nom)
    and_clauses.extend(_fast_food_exclusion_filter())

    # Stratégie d'affichage par type :
    #   restaurant → uniquement si confirmé OU (rating >= 4.0 ET 100+ avis)
    #   bar/cafe/rooftop → tous
    restaurant_quality = {
        "$or": [
            {"has_terrace_confirmed": True},
            {"$and": [{"google_rating": {"$gte": 4.0}}, {"google_ratings_count": {"$gte": 100}}]},
        ]
    }
    type_policy = {
        "$or": [
            {"type": {"$in": ["bar", "cafe", "rooftop"]}},
            {"$and": [{"type": "restaurant"}, restaurant_quality]},
        ]
    }
    and_clauses.append(type_policy)

    if and_clauses:
        query["$and"] = and_clauses

    target_time = parse_at_time(at_time)

    # Cap hard à 2000 (pour mode "toutes les villes globalement")
    effective_limit = min(limit, 2000)
    cursor = db.terraces.find(query, {"_id": 0}).limit(effective_limit + 50)
    # +50 buffer pour absorber les filtres Python (sun_status, radius_km)
    terraces = await cursor.to_list(effective_limit + 50)

    result = []
    for t in terraces:
        # Distance si position fournie
        distance = None
        if lat is not None and lng is not None:
            distance = round(haversine_km(lat, lng, t["lat"], t["lng"]), 2)
            if radius_km is not None and distance > radius_km:
                continue

        sun_info = compute_sun_status_dynamic(
            t["lat"], t["lng"], t["orientation_degrees"], target_time
        )
        sun_info = apply_shadow_override(sun_info, t, target_time)

        if sun_status and sun_info["status"] != sun_status:
            continue

        t_out = terrace_to_public(t)
        t_out["distance_km"] = distance
        t_out["sun_status"] = sun_info["status"]
        t_out["is_sunny"] = sun_info["is_sunny"]
        t_out["sun_azimuth"] = sun_info["sun_azimuth"]
        t_out["sun_altitude"] = sun_info["sun_altitude"]
        t_out["next_sunny_time"] = sun_info.get("next_sunny_time")
        t_out["sunny_until"] = sun_info.get("sunny_until")
        t_out["shadow_analyzed"] = sun_info.get("shadow_analyzed", False)
        t_out["shadow_override"] = sun_info.get("shadow_override", False)
        result.append(t_out)

    # Tri : partenaires en premier, puis ensoleillées, puis par distance
    result.sort(key=lambda x: (
        0 if x.get("is_partner") else 1,
        {"sunny": 0, "soon": 1, "shade": 2}.get(x["sun_status"], 3),
        x.get("distance_km") or 999,
    ))

    # Cap final à effective_limit après tri
    result = result[:effective_limit]

    return {
        "terraces": result,
        "count": len(result),
        "at_time": target_time.isoformat(),
        "query": {
            "city": city,
            "type": type,
            "sun_status": sun_status,
            "bbox": (
                [lat_min, lng_min, lat_max, lng_max]
                if (lat_min is not None and lng_min is not None)
                else None
            ),
        },
    }


@api_router.get("/terraces/search")
async def search_terraces(
    q: str = Query(..., min_length=1, description="Query string (name)"),
    city: Optional[str] = Query(None),
    at_time: Optional[str] = Query(None),
    limit: int = Query(8, ge=1, le=20),
):
    """
    Recherche full-text sur le nom (case-insensitive, regex).
    Retourne max `limit` résultats avec sun_status calculé pour `at_time` (ou maintenant).
    """
    import re
    safe = re.escape(q.strip())
    query_filter: dict = {
        "name": {"$regex": safe, "$options": "i"},
        "terrace_source": {"$nin": ["street_view_no_image", "community_hidden"]},
        "$and": _fast_food_exclusion_filter(),
    }
    if city:
        query_filter["city"] = city

    target_time = parse_at_time(at_time)

    # Sort: confirmed first (has_terrace_confirmed=true), then by google_rating desc.
    # Garantit que les établissements vérifiés apparaissent en tête du top N.
    cursor = (
        db.terraces.find(query_filter, {"_id": 0, "community_photos": 0})
        .sort([("has_terrace_confirmed", -1), ("google_rating", -1)])
        .limit(limit)
    )
    terraces = await cursor.to_list(limit)

    results = []
    for t in terraces:
        sun_info = compute_sun_status_dynamic(
            t["lat"], t["lng"], t["orientation_degrees"], target_time
        )
        sun_info = apply_shadow_override(sun_info, t, target_time)
        t_out = terrace_to_public(t)
        t_out["sun_status"] = sun_info["status"]
        t_out["is_sunny"] = sun_info["is_sunny"]
        t_out["sun_azimuth"] = sun_info["sun_azimuth"]
        t_out["sun_altitude"] = sun_info["sun_altitude"]
        t_out["next_sunny_time"] = sun_info.get("next_sunny_time")
        t_out["sunny_until"] = sun_info.get("sunny_until")
        t_out["shadow_analyzed"] = sun_info.get("shadow_analyzed", False)
        t_out["shadow_override"] = sun_info.get("shadow_override", False)
        results.append(t_out)

    # Sort: sunny first, then soon, then shade
    results.sort(key=lambda x: {"sunny": 0, "soon": 1, "shade": 2}.get(x["sun_status"], 3))

    return {"results": results, "count": len(results), "q": q}


@api_router.get("/terraces/{terrace_id}")
async def get_terrace(
    terrace_id: str,
    at_time: Optional[str] = Query(None),
):
    """Détail d'une terrasse avec prévisions horaires et plage ensoleillée du jour."""
    doc = await db.terraces.find_one({"id": terrace_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Terrace not found")

    target_time = parse_at_time(at_time)

    sun_info = compute_sun_status_dynamic(
        doc["lat"], doc["lng"], doc["orientation_degrees"], target_time
    )
    sun_info = apply_shadow_override(sun_info, doc, target_time)
    schedule = compute_sun_schedule_for_day(
        doc["lat"], doc["lng"], doc["orientation_degrees"], target_time
    )
    hourly = compute_hourly_forecast(
        doc["lat"], doc["lng"], doc["orientation_degrees"], target_time
    )

    result = terrace_to_public(doc)
    result["at_time"] = target_time.isoformat()
    result["sun_status"] = sun_info["status"]
    result["is_sunny"] = sun_info["is_sunny"]
    result["sun_azimuth"] = sun_info["sun_azimuth"]
    result["sun_altitude"] = sun_info["sun_altitude"]
    result["next_sunny_time"] = sun_info.get("next_sunny_time")
    result["sunny_until"] = sun_info.get("sunny_until")
    result["shadow_analyzed"] = sun_info.get("shadow_analyzed", False)
    result["shadow_override"] = sun_info.get("shadow_override", False)
    result["sun_schedule_today"] = schedule
    result["hourly_forecast"] = hourly
    return result


@api_router.get("/sun-position")
async def sun_position_endpoint(
    lat: float = Query(...),
    lng: float = Query(...),
    at_time: Optional[str] = Query(None),
):
    """Position du soleil à un instant et lieu donné."""
    target = parse_at_time(at_time)
    return {
        "at_time": target.isoformat(),
        "position": get_sun_position(lat, lng, target),
    }


@api_router.post("/sun-check")
async def sun_check_endpoint(body: dict):
    """
    Calcule si une terrasse est ensoleillée.
    Body: {lat, lng, orientation_degrees, at_time?}
    """
    lat = body.get("lat")
    lng = body.get("lng")
    ori = body.get("orientation_degrees")
    if lat is None or lng is None or ori is None:
        raise HTTPException(400, "lat, lng, orientation_degrees required")
    target = parse_at_time(body.get("at_time"))
    result = is_terrace_sunny(float(lat), float(lng), float(ori), target)
    result["at_time"] = target.isoformat()
    return result


# ---- Shadow overlay (OSM 3D ray-casting for live map overlays) ------------
_SHADOW_CACHE: dict[str, tuple[float, dict]] = {}
_SHADOW_CACHE_TTL = 15 * 60  # 15 min
_SHADOW_CACHE_MAX = 64


def _shadow_cache_key(bbox: tuple, t_bucket: int) -> str:
    # Round bbox to 3 decimals (≈110m) to maximize cache hits
    bb = tuple(round(x, 3) for x in bbox)
    return f"{bb}_{t_bucket}"


@api_router.get("/shadows")
async def shadows_overlay(
    lat_min: float = Query(..., description="bbox south"),
    lat_max: float = Query(..., description="bbox north"),
    lng_min: float = Query(..., description="bbox west"),
    lng_max: float = Query(..., description="bbox east"),
    at_time: Optional[str] = Query(None, description="ISO ou HH:MM; default now"),
):
    """
    Overlay d'ombres projetées pour les bâtiments OSM du bbox à un instant donné.
    Retourne des polygones GeoJSON-like (lat/lng) semi-opaques à dessiner sur la carte.

    Cache en mémoire par (bbox_arrondi, 15min_bucket). TTL 15min.

    Garde-fou : bbox max 0.06° (≈6 km) pour protéger Overpass.
    """
    span_lat = lat_max - lat_min
    span_lng = lng_max - lng_min
    # Garde-fou 0.08° ≈ 9 km côté avec tolérance float. Permet un rendu
    # quartier/arrondissement dès l'ouverture de l'app sans zoom extrême.
    MAX_SPAN = 0.0801
    if span_lat <= 0 or span_lng <= 0 or span_lat > MAX_SPAN or span_lng > MAX_SPAN:
        return {
            "polygons": [],
            "sun": {"az": None, "el": None},
            "building_count": 0,
            "reason": "bbox_invalid_or_too_large",
        }

    target = parse_at_time(at_time)
    target_utc = target.astimezone(timezone.utc) if target.tzinfo else target.replace(tzinfo=timezone.utc)
    # 15-min time bucket (YYYYMMDDhhmm/15)
    t_bucket = int(target_utc.timestamp() // (15 * 60))

    import time as _time
    key = _shadow_cache_key((lat_min, lng_min, lat_max, lng_max), t_bucket)
    now = _time.time()
    cached = _SHADOW_CACHE.get(key)
    if cached and (now - cached[0]) < _SHADOW_CACHE_TTL:
        return {**cached[1], "cached": True}

    # Compute (can be 2-10s — OSM Overpass network call)
    try:
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            compute_shadow_overlay,
            lat_min,
            lng_min,
            lat_max,
            lng_max,
            target_utc,
        )
    except Exception as e:
        logger.warning(f"Shadow overlay failed: {e}")
        return {"polygons": [], "sun": {"az": None, "el": None}, "building_count": 0, "error": str(e)[:200]}

    # Prune cache if too big
    if len(_SHADOW_CACHE) >= _SHADOW_CACHE_MAX:
        oldest_key = min(_SHADOW_CACHE, key=lambda k: _SHADOW_CACHE[k][0])
        _SHADOW_CACHE.pop(oldest_key, None)
    _SHADOW_CACHE[key] = (now, result)

    return {**result, "cached": False, "at_time": target_utc.isoformat()}


@api_router.get("/next-sunny")
async def next_sunny(
    city: Optional[str] = Query(None),
    at_time: Optional[str] = Query(None, description="ISO datetime de référence (défaut: now)"),
):
    """
    Trouve la prochaine terrasse au soleil (utile pour l'état nocturne).
    Retourne la plus proche dans le temps, aujourd'hui ou demain matin.
    """
    from datetime import timedelta as _td

    query = {}
    if city:
        query["city"] = city

    ref = parse_at_time(at_time)
    cursor = db.terraces.find(query, {"_id": 0})
    terraces = await cursor.to_list(1000)

    if not terraces:
        return {"found": False}

    best_time = None
    best_terrace = None

    # Cherche sur les prochaines 36h, pas de 15 minutes
    for offset_min in range(0, 36 * 60, 15):
        probe = ref + _td(minutes=offset_min)
        for t in terraces:
            res = is_terrace_sunny(
                t["lat"], t["lng"], t["orientation_degrees"], probe
            )
            if res["is_sunny"]:
                if best_time is None or probe < best_time:
                    best_time = probe
                    best_terrace = t
        if best_time is not None:
            break

    if best_time is None or best_terrace is None:
        return {"found": False}

    is_tomorrow = best_time.date() > ref.date()
    return {
        "found": True,
        "first_sunny_time": best_time.strftime("%H:%M"),
        "first_sunny_iso": best_time.isoformat(),
        "is_tomorrow": is_tomorrow,
        "terrace_id": best_terrace["id"],
        "terrace_name": best_terrace["name"],
        "terrace_type": best_terrace["type"],
        "terrace_photo": best_terrace.get("photo_url"),
    }


# ====================================================================
# CROWDSOURCING & PARTENAIRES PRO
# ====================================================================


@api_router.post("/terraces/{terrace_id}/report")
async def report_terrace(terrace_id: str, body: dict):
    """
    Signaler une terrasse : confirmed | wrong_orientation | no_terrace.
    Stocke le report; si 3+ reports no_terrace → on masque automatiquement.
    Body: { type: "confirmed"|"wrong_orientation"|"no_terrace", user_id?: str }
    """
    report_type = body.get("type")
    if report_type not in ("confirmed", "wrong_orientation", "no_terrace"):
        raise HTTPException(400, "Invalid report type")

    terrace = await db.terraces.find_one({"id": terrace_id}, {"_id": 0, "id": 1, "name": 1})
    if not terrace:
        raise HTTPException(404, "Terrace not found")

    await db.reports.insert_one({
        "id": str(uuid.uuid4()),
        "terrace_id": terrace_id,
        "type": report_type,
        "user_id": body.get("user_id") or "anonymous",
        "created_at": datetime.now(pytz.utc),
    })

    # Agrégation en temps réel
    counts = {"confirmed": 0, "wrong_orientation": 0, "no_terrace": 0}
    async for r in db.reports.find({"terrace_id": terrace_id}, {"type": 1, "_id": 0}):
        t = r.get("type")
        if t in counts:
            counts[t] += 1

    update = {
        "reports": counts,
        "reports_updated_at": datetime.now(pytz.utc),
    }
    # Auto-masquage si 3+ no_terrace (et pas de compensation confirmed)
    if counts["no_terrace"] >= 3 and counts["no_terrace"] > counts["confirmed"]:
        update["has_terrace_confirmed"] = False
        update["terrace_source"] = "community_hidden"

    await db.terraces.update_one({"id": terrace_id}, {"$set": update})
    return {"ok": True, "reports": counts, "hidden": counts["no_terrace"] >= 3}


@api_router.post("/terraces/{terrace_id}/photo")
async def upload_terrace_photo(terrace_id: str, body: dict):
    """
    Upload base64 photo → stocké dans terraces.community_photos[].
    Body: { image_base64: str, user_id?: str, caption?: str }
    """
    image_b64 = (body.get("image_base64") or "").strip()
    if not image_b64:
        raise HTTPException(400, "image_base64 required")
    if len(image_b64) > 3_500_000:  # ~2.5MB image max
        raise HTTPException(413, "Image too large (max ~2.5MB)")

    terrace = await db.terraces.find_one({"id": terrace_id}, {"_id": 0, "id": 1})
    if not terrace:
        raise HTTPException(404, "Terrace not found")

    photo = {
        "id": str(uuid.uuid4()),
        "image_base64": image_b64,
        "user_id": body.get("user_id") or "anonymous",
        "caption": (body.get("caption") or "")[:200],
        "created_at": datetime.now(pytz.utc),
    }
    await db.terraces.update_one(
        {"id": terrace_id},
        {"$push": {"community_photos": photo}},
    )
    return {"ok": True, "photo_id": photo["id"]}


@api_router.post("/terraces/submit")
async def submit_terrace(body: dict):
    """
    Soumission d'une nouvelle terrasse par un utilisateur.
    Body: { name, type, orientation_label|orientation_degrees, lat, lng, city, photo_base64?, user_id? }
    """
    name = (body.get("name") or "").strip()
    ttype = (body.get("type") or "bar").lower()
    city = (body.get("city") or "").strip()
    lat = body.get("lat")
    lng = body.get("lng")
    if not name or not city or lat is None or lng is None:
        raise HTTPException(400, "name, city, lat, lng required")

    # Orientation: accepte degrés directs ou label
    ori_deg = body.get("orientation_degrees")
    if ori_deg is None:
        label = (body.get("orientation_label") or "").lower()
        label_map = {
            "nord": 0, "nord-est": 45, "est": 90, "sud-est": 135,
            "sud": 180, "plein sud": 180, "sud-ouest": 225,
            "ouest": 270, "nord-ouest": 315,
        }
        ori_deg = label_map.get(label, 180)
    ori_deg = float(ori_deg) % 360

    user_id = body.get("user_id") or "anonymous"
    photo_b64 = body.get("photo_base64")

    doc = {
        "id": str(uuid.uuid4()),
        "name": name[:120],
        "lat": float(lat),
        "lng": float(lng),
        "orientation_degrees": ori_deg,
        "orientation_label": orientation_label(ori_deg),
        "type": ttype if ttype in ("bar", "cafe", "restaurant", "rooftop") else "bar",
        "city": city,
        "arrondissement": None,
        "address": body.get("address") or city,
        "google_rating": 4.0,
        "google_ratings_count": 0,
        "photos": [],
        "community_photos": ([{
            "id": str(uuid.uuid4()),
            "image_base64": photo_b64,
            "user_id": user_id,
            "created_at": datetime.now(pytz.utc),
        }] if photo_b64 else []),
        "photo_url": "https://images.unsplash.com/photo-1551024709-8f23befc6f87?w=800&q=80",
        "has_cover": False,
        "capacity_estimate": 30,
        "has_terrace_confirmed": True,
        "terrace_source": "user_submission",
        "status": "pending_review",
        "submitted_by": user_id,
        "ai_description": None,
        "created_at": datetime.now(pytz.utc),
    }
    await db.terraces.insert_one(doc)
    return {"ok": True, "id": doc["id"]}


@api_router.post("/pro/contact")
async def pro_contact(body: dict):
    """
    Formulaire restaurateur : sauvegarde en DB (pro_leads).
    Body: { establishment_name, email, city, message? }
    """
    name = (body.get("establishment_name") or "").strip()
    email = (body.get("email") or "").strip().lower()
    city = (body.get("city") or "").strip()
    if not name or not email or "@" not in email:
        raise HTTPException(400, "establishment_name, email (valid), city required")

    lead = {
        "id": str(uuid.uuid4()),
        "establishment_name": name[:120],
        "email": email[:120],
        "city": city[:80],
        "message": (body.get("message") or "")[:2000],
        "status": "new",
        "created_at": datetime.now(pytz.utc),
    }
    await db.pro_leads.insert_one(lead)
    logger.info(f"New pro lead: {name} ({email}) in {city}")
    return {"ok": True, "id": lead["id"]}


@api_router.get("/pro/leads")
async def list_pro_leads():
    """Liste des demandes restaurateurs (pour modération future)."""
    cursor = db.pro_leads.find({}, {"_id": 0}).sort("created_at", -1).limit(500)
    leads = await cursor.to_list(500)
    return {"leads": leads, "count": len(leads)}


# ===== Notifications (push tokens registry) ======================================


class PushRegisterRequest(BaseModel):
    push_token: str
    city: Optional[str] = None
    preferences: Optional[dict] = None


@api_router.post("/notifications/register")
async def register_push_token(req: PushRegisterRequest):
    """Enregistre un push token Expo pour l'envoi de notifications quotidiennes.
    Idempotent: upsert sur push_token."""
    token = (req.push_token or "").strip()
    if not token or (not token.startswith("ExponentPushToken[") and not token.startswith("ExpoPushToken[")):
        raise HTTPException(400, "Invalid Expo push_token")

    now = datetime.now(timezone.utc)
    existing = await db.push_tokens.find_one({"token": token}, {"_id": 0, "id": 1})
    if existing:
        await db.push_tokens.update_one(
            {"token": token},
            {
                "$set": {
                    "city": req.city,
                    "preferences": req.preferences or {},
                    "updated_at": now,
                }
            },
        )
        return {"ok": True, "id": existing["id"], "updated": True}

    doc = {
        "id": str(uuid.uuid4()),
        "token": token,
        "city": req.city,
        "preferences": req.preferences or {},
        "created_at": now,
        "updated_at": now,
        "enabled": True,
    }
    await db.push_tokens.insert_one(doc)
    return {"ok": True, "id": doc["id"], "updated": False}


# ===== Favorites (client-side AsyncStorage, backend resolves statuses) ==========


class FavoritesRequest(BaseModel):
    ids: List[str]


@api_router.post("/terraces/favorites")
async def get_favorite_terraces(req: FavoritesRequest, at_time: Optional[str] = Query(None)):
    """Retourne les terrasses favorites (par id) avec leur sun_status calculé."""
    ids = [i for i in (req.ids or []) if isinstance(i, str) and i]
    if not ids:
        return {"terraces": [], "count": 0}
    ids = ids[:200]  # guard
    target_time = parse_at_time(at_time)
    cursor = db.terraces.find({"id": {"$in": ids}}, {"_id": 0, "community_photos": 0})
    docs = await cursor.to_list(len(ids))
    # Preserve input order
    by_id = {d["id"]: d for d in docs}
    results = []
    for terrace_id in ids:
        t = by_id.get(terrace_id)
        if not t:
            continue
        sun_info = compute_sun_status_dynamic(
            t["lat"], t["lng"], t["orientation_degrees"], target_time
        )
        sun_info = apply_shadow_override(sun_info, t, target_time)
        out = terrace_to_public(t)
        out["sun_status"] = sun_info["status"]
        out["is_sunny"] = sun_info["is_sunny"]
        out["sun_azimuth"] = sun_info["sun_azimuth"]
        out["sun_altitude"] = sun_info["sun_altitude"]
        out["next_sunny_time"] = sun_info.get("next_sunny_time")
        out["sunny_until"] = sun_info.get("sunny_until")
        out["shadow_analyzed"] = sun_info.get("shadow_analyzed", False)
        out["shadow_override"] = sun_info.get("shadow_override", False)
        results.append(out)
    return {"terraces": results, "count": len(results)}




@api_router.get("/weather/{city}")
async def get_weather(city: str):
    """Météo actuelle via Open-Meteo (gratuit, sans clé)."""
    if city not in CITY_CENTERS:
        raise HTTPException(404, f"City not supported. Available: {list(CITY_CENTERS.keys())}")

    coords = CITY_CENTERS[city]
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={coords['lat']}&longitude={coords['lng']}"
        f"&current=temperature_2m,apparent_temperature,is_day,cloud_cover,uv_index,weather_code,wind_speed_10m"
        f"&timezone=Europe%2FParis"
    )
    async with httpx.AsyncClient(timeout=10) as http:
        try:
            r = await http.get(url)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            logger.error(f"Open-Meteo error: {e}")
            raise HTTPException(502, "Weather service unavailable")

    current = data.get("current", {})
    # Code météo OpenMeteo → label simple
    code = current.get("weather_code", 0)
    weather_labels = {
        0: "Ciel dégagé", 1: "Plutôt dégagé", 2: "Partiellement nuageux", 3: "Couvert",
        45: "Brouillard", 48: "Brouillard givrant",
        51: "Bruine légère", 53: "Bruine modérée", 55: "Bruine dense",
        61: "Pluie légère", 63: "Pluie modérée", 65: "Forte pluie",
        71: "Neige légère", 73: "Neige modérée", 75: "Forte neige",
        80: "Averses légères", 81: "Averses modérées", 82: "Fortes averses",
        95: "Orage", 96: "Orage avec grêle", 99: "Violent orage",
    }
    return {
        "city": city,
        "temperature": current.get("temperature_2m"),
        "apparent_temperature": current.get("apparent_temperature"),
        "cloud_cover": current.get("cloud_cover"),
        "uv_index": current.get("uv_index"),
        "wind_speed": current.get("wind_speed_10m"),
        "is_day": bool(current.get("is_day", 1)),
        "weather_code": code,
        "weather_label": weather_labels.get(code, "Inconnu"),
        "updated_at": current.get("time"),
    }


# =========================
# AI Description Generation (Claude)
# =========================
async def generate_ai_description(terrace: dict) -> str:
    """Génère une description lifestyle de 2 lignes via Claude Sonnet 4."""
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage

        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"terrace-{terrace['id']}",
            system_message=(
                "Tu es un expert lifestyle nantais qui écrit des descriptions courtes et élégantes "
                "pour Soleia, une app premium de recherche de terrasses ensoleillées. "
                "Style: premium, inspiré Airbnb, factuel mais sensoriel. "
                "Mentionne la Loire, l'île de Nantes, les quais, Graslin, le Bouffay quand c'est pertinent. "
                "Réponds UNIQUEMENT avec la description (2 phrases, 30 mots max), "
                "sans guillemets ni préambule."
            ),
        ).with_model("anthropic", "claude-4-sonnet-20250514")

        ori_label = orientation_label(terrace["orientation_degrees"])
        type_fr = {"bar": "bar", "cafe": "café", "restaurant": "restaurant", "rooftop": "rooftop"}.get(
            terrace["type"], terrace["type"]
        )
        cover = "avec auvent" if terrace.get("has_cover") else "en plein air"
        prompt = (
            f"Décris la terrasse du {type_fr} '{terrace['name']}' "
            f"situé dans le quartier {terrace.get('arrondissement', '')} à {terrace['city']}. "
            f"Orientation: {ori_label}. Aménagement: {cover}. "
            f"Note Google: {terrace['google_rating']}/5. "
            f"Capacité estimée: {terrace.get('capacity_estimate', 30)} places."
        )
        response = await chat.send_message(UserMessage(text=prompt))
        return response.strip()
    except Exception as e:
        logger.warning(f"AI description failed for {terrace.get('name')}: {e}")
        ori = orientation_label(terrace.get("orientation_degrees", 180))
        return f"Terrasse orientée {ori.lower()}, idéale pour profiter du soleil. Ambiance {terrace.get('type', 'bar')} dans le quartier {terrace.get('arrondissement', '')}."


@api_router.post("/terraces/{terrace_id}/generate-description")
async def generate_description_endpoint(terrace_id: str):
    """Génère et sauvegarde une description IA pour une terrasse."""
    doc = await db.terraces.find_one({"id": terrace_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Terrace not found")

    description = await generate_ai_description(doc)
    await db.terraces.update_one(
        {"id": terrace_id}, {"$set": {"ai_description": description}}
    )
    return {"id": terrace_id, "ai_description": description}


# =========================
# Seed endpoint
# =========================
@api_router.post("/seed/nantes")
async def seed_nantes(force: bool = False):
    """Seed des 20 terrasses nantaises. force=true pour écraser."""
    count = await db.terraces.count_documents({"city": "Nantes"})
    if count > 0 and not force:
        return {"status": "already_seeded", "existing_count": count}

    if force:
        await db.terraces.delete_many({"city": "Nantes"})

    docs_to_insert = []
    for data in NANTES_TERRACES:
        doc = {
            "id": str(uuid.uuid4()),
            "name": data["name"],
            "lat": data["lat"],
            "lng": data["lng"],
            "orientation_degrees": data["orientation_degrees"],
            "orientation_label": orientation_label(data["orientation_degrees"]),
            "type": data["type"],
            "city": data["city"],
            "arrondissement": data.get("arrondissement"),
            "address": data["address"],
            "google_rating": data["google_rating"],
            "photo_url": data["photo_url"],
            "has_cover": data.get("has_cover", False),
            "capacity_estimate": data.get("capacity_estimate", 30),
            "ai_description": None,
            "created_at": datetime.now(pytz.utc),
        }
        docs_to_insert.append(doc)

    await db.terraces.insert_many(docs_to_insert)

    return {
        "status": "seeded",
        "inserted": len(docs_to_insert),
        "city": "Nantes",
    }


# Alias rétro-compat : /api/seed/paris délègue vers Nantes (ancien endpoint)
@api_router.post("/seed/paris")
async def seed_paris(force: bool = False):
    return await seed_nantes(force=force)


@api_router.post("/seed/generate-all-descriptions")
async def seed_all_descriptions(limit: int = 20):
    """Génère des descriptions IA pour toutes les terrasses sans description."""
    cursor = db.terraces.find({"ai_description": None}, {"_id": 0}).limit(limit)
    terraces = await cursor.to_list(limit)

    results = []
    # Sequential pour éviter rate limit
    for t in terraces:
        description = await generate_ai_description(t)
        await db.terraces.update_one(
            {"id": t["id"]}, {"$set": {"ai_description": description}}
        )
        results.append({"id": t["id"], "name": t["name"], "description": description})

    return {"count": len(results), "results": results}


# =========================
# Startup: auto-seed if empty
# =========================
@app.on_event("startup")
async def on_startup():
    # Ensure MongoDB indexes for performance
    try:
        existing = await db.terraces.index_information()
        wanted = [
            ([("lat", 1), ("lng", 1)], "lat_lng"),
            ([("city", 1), ("type", 1)], "city_type"),
        ]
        for spec, name in wanted:
            if name not in existing:
                await db.terraces.create_index(spec, name=name)
                logger.info(f"Created index {name}")
    except Exception as e:
        logger.warning(f"Index creation skipped: {e}")

    count = await db.terraces.count_documents({"city": "Nantes"})
    if count == 0:
        logger.info("Auto-seeding Nantes terraces on startup...")
        docs_to_insert = []
        for data in NANTES_TERRACES:
            doc = {
                "id": str(uuid.uuid4()),
                "name": data["name"],
                "lat": data["lat"],
                "lng": data["lng"],
                "orientation_degrees": data["orientation_degrees"],
                "orientation_label": orientation_label(data["orientation_degrees"]),
                "type": data["type"],
                "city": data["city"],
                "arrondissement": data.get("arrondissement"),
                "address": data["address"],
                "google_rating": data["google_rating"],
                "photo_url": data["photo_url"],
                "has_cover": data.get("has_cover", False),
                "capacity_estimate": data.get("capacity_estimate", 30),
                "ai_description": None,
                "created_at": datetime.now(pytz.utc),
            }
            docs_to_insert.append(doc)
        await db.terraces.insert_many(docs_to_insert)
        logger.info(f"Seeded {len(docs_to_insert)} Nantes terraces.")


@app.on_event("shutdown")
async def on_shutdown():
    client.close()


# Mount router
app.include_router(api_router)
app.include_router(auth_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
