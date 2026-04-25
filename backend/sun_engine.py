"""
SunTerrace - Sun Calculation Engine
Calcule la position du soleil et détermine si une terrasse est ensoleillée.

Logique:
- Utilise pysolar pour calculer azimut (0-360°, 0=Nord, 90=Est, 180=Sud, 270=Ouest)
  et altitude (hauteur au-dessus de l'horizon, 0-90°) du soleil.
- Une terrasse est "au soleil" si:
  1. altitude > 10° (soleil au-dessus de l'horizon, pas trop bas)
  2. azimut du soleil est face à l'orientation de la terrasse avec une tolérance de ±60°
"""

from datetime import datetime, timedelta, timezone
from pysolar.solar import get_altitude, get_azimuth
import pytz

# Tolérance de l'angle pour considérer une terrasse "face au soleil" (degrés)
ORIENTATION_TOLERANCE = 60
# Hauteur solaire minimale pour considérer la terrasse ensoleillée (degrés)
MIN_ALTITUDE = 10

# Fuseau horaire Europe/Paris (villes françaises)
PARIS_TZ = pytz.timezone("Europe/Paris")


def _ensure_aware(dt: datetime) -> datetime:
    """S'assurer que datetime est timezone-aware (Europe/Paris si naive)."""
    if dt.tzinfo is None:
        return PARIS_TZ.localize(dt)
    return dt


def get_sun_position(lat: float, lng: float, at_time: datetime) -> dict:
    """
    Retourne position du soleil à un moment donné.
    Returns: {azimuth, altitude, is_above_horizon}
    """
    at_time = _ensure_aware(at_time)
    altitude = float(get_altitude(lat, lng, at_time))
    azimuth = float(get_azimuth(lat, lng, at_time))
    # Normaliser azimuth entre 0-360
    azimuth = azimuth % 360
    return {
        "azimuth": round(azimuth, 1),
        "altitude": round(altitude, 1),
        "is_above_horizon": bool(altitude > 0),
    }


def angle_diff(a: float, b: float) -> float:
    """Différence angulaire minimale entre deux angles (0-180°)."""
    d = abs(a - b) % 360
    return d if d <= 180 else 360 - d


def is_terrace_sunny(
    lat: float,
    lng: float,
    orientation_degrees: float,
    at_time: datetime,
) -> dict:
    """
    Détermine si une terrasse est au soleil à un instant donné.
    Returns: {is_sunny, sun_azimuth, sun_altitude, angle_to_sun, reason}
    """
    pos = get_sun_position(lat, lng, at_time)

    # Vérifier si le soleil est suffisamment haut
    if pos["altitude"] < MIN_ALTITUDE:
        return {
            "is_sunny": False,
            "sun_azimuth": pos["azimuth"],
            "sun_altitude": pos["altitude"],
            "angle_to_sun": None,
            "reason": "sun_too_low" if pos["altitude"] >= 0 else "sun_below_horizon",
        }

    # Vérifier si l'orientation est face au soleil
    diff = angle_diff(pos["azimuth"], orientation_degrees)
    is_facing_sun = diff <= ORIENTATION_TOLERANCE

    return {
        "is_sunny": bool(is_facing_sun),
        "sun_azimuth": pos["azimuth"],
        "sun_altitude": pos["altitude"],
        "angle_to_sun": round(diff, 1),
        "reason": "facing_sun" if is_facing_sun else "facing_away",
    }


def compute_sun_schedule_for_day(
    lat: float,
    lng: float,
    orientation_degrees: float,
    day: datetime,
) -> dict:
    """
    Calcule la plage horaire où la terrasse est ensoleillée aujourd'hui.
    Échantillonne toutes les 15 minutes de 6h à 22h.
    Returns: {sunny_hours: [{start, end, duration_minutes}], total_minutes, first_sunny, last_sunny}
    """
    day = _ensure_aware(day)
    start_day = day.replace(hour=6, minute=0, second=0, microsecond=0)
    end_day = day.replace(hour=22, minute=0, second=0, microsecond=0)

    step = timedelta(minutes=15)
    intervals = []
    current = start_day
    current_start = None

    while current <= end_day:
        result = is_terrace_sunny(lat, lng, orientation_degrees, current)
        if result["is_sunny"]:
            if current_start is None:
                current_start = current
        else:
            if current_start is not None:
                intervals.append((current_start, current))
                current_start = None
        current += step

    # Fermer si soleil encore en fin de journée
    if current_start is not None:
        intervals.append((current_start, end_day))

    sunny_hours = []
    total_minutes = 0
    for s, e in intervals:
        duration = int((e - s).total_seconds() / 60)
        total_minutes += duration
        sunny_hours.append(
            {
                "start": s.strftime("%H:%M"),
                "end": e.strftime("%H:%M"),
                "duration_minutes": duration,
            }
        )

    return {
        "sunny_hours": sunny_hours,
        "total_minutes": total_minutes,
        "first_sunny": sunny_hours[0]["start"] if sunny_hours else None,
        "last_sunny": sunny_hours[-1]["end"] if sunny_hours else None,
    }


def compute_hourly_forecast(
    lat: float,
    lng: float,
    orientation_degrees: float,
    day: datetime,
) -> list:
    """
    Prévisions heure par heure pour le jour donné (6h-22h).
    Returns: [{hour, is_sunny, sun_azimuth, sun_altitude}]
    """
    day = _ensure_aware(day)
    forecast = []
    for h in range(6, 23):
        t = day.replace(hour=h, minute=0, second=0, microsecond=0)
        result = is_terrace_sunny(lat, lng, orientation_degrees, t)
        forecast.append(
            {
                "hour": f"{h:02d}:00",
                "is_sunny": result["is_sunny"],
                "sun_azimuth": result["sun_azimuth"],
                "sun_altitude": result["sun_altitude"],
            }
        )
    return forecast


def compute_sun_status_dynamic(
    lat: float,
    lng: float,
    orientation_degrees: float,
    at_time: datetime,
) -> dict:
    """
    Statut dynamique pour afficher sur la carte: 'sunny', 'soon' (dans 1h), 'shade'.
    + prochaine transition (quand la terrasse passera au soleil/à l'ombre)
    """
    at_time = _ensure_aware(at_time)
    now_status = is_terrace_sunny(lat, lng, orientation_degrees, at_time)

    if now_status["is_sunny"]:
        status = "sunny"
    else:
        # Vérifier si soleil dans les 60 prochaines minutes
        soon = False
        next_sunny_time = None
        for mins in [15, 30, 45, 60]:
            future = at_time + timedelta(minutes=mins)
            future_status = is_terrace_sunny(lat, lng, orientation_degrees, future)
            if future_status["is_sunny"]:
                soon = True
                next_sunny_time = future.strftime("%H:%M")
                break
        status = "soon" if soon else "shade"
        now_status["next_sunny_time"] = next_sunny_time

    # Si actuellement sunny, calculer jusqu'à quand
    if now_status["is_sunny"]:
        sunny_until = None
        for mins in [15, 30, 45, 60, 90, 120, 180, 240]:
            future = at_time + timedelta(minutes=mins)
            future_status = is_terrace_sunny(lat, lng, orientation_degrees, future)
            if not future_status["is_sunny"]:
                sunny_until = future.strftime("%H:%M")
                break
        now_status["sunny_until"] = sunny_until

    return {
        "status": status,
        "is_sunny": now_status["is_sunny"],
        "sun_azimuth": now_status["sun_azimuth"],
        "sun_altitude": now_status["sun_altitude"],
        "next_sunny_time": now_status.get("next_sunny_time"),
        "sunny_until": now_status.get("sunny_until"),
    }
