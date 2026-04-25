"""SunTerrace backend API tests (pytest)."""
import os
import pytest
import requests

BASE_URL = "https://sunny-terraces.preview.emergentagent.com"


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# ---- health & cities ----
def test_health(client):
    r = client.get(f"{BASE_URL}/api/")
    assert r.status_code == 200
    data = r.json()
    assert data["app"] == "SunTerrace API"


def test_list_cities(client):
    r = client.get(f"{BASE_URL}/api/cities")
    assert r.status_code == 200
    cities = r.json()
    assert isinstance(cities, list)
    assert len(cities) == 12
    names = [c["name"] for c in cities]
    assert "Nantes" in names and "Lyon" in names
    for c in cities:
        assert "lat" in c and "lng" in c


# ---- terraces listing ----
def test_list_terraces_paris(client):
    r = client.get(f"{BASE_URL}/api/terraces", params={"city": "Nantes"})
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 20
    assert len(body["terraces"]) == 20
    t = body["terraces"][0]
    for key in ["id", "name", "lat", "lng", "orientation_degrees", "sun_status",
                "is_sunny", "sun_azimuth", "sun_altitude", "photo_url", "type",
                "orientation_label"]:
        assert key in t, f"Missing key {key}"
    assert t["sun_status"] in ["sunny", "soon", "shade"]
    # ensure no mongo _id leak
    assert "_id" not in t


def test_list_terraces_at_14h(client):
    r = client.get(f"{BASE_URL}/api/terraces",
                   params={"city": "Nantes", "at_time": "14:00"})
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 20
    # In summer/daytime at 14h (Nantes sun around south), expect some sunny
    sunny_count = sum(1 for t in body["terraces"] if t["sun_status"] == "sunny")
    # The 14:00 test expects "plusieurs sunny"
    assert sunny_count >= 1, f"Expected at least 1 sunny at 14:00 got {sunny_count}"


def test_list_terraces_at_02h_all_shade(client):
    r = client.get(f"{BASE_URL}/api/terraces",
                   params={"city": "Nantes", "at_time": "02:00"})
    assert r.status_code == 200
    body = r.json()
    for t in body["terraces"]:
        assert t["sun_status"] == "shade", f"{t['name']} not shade at 02:00"
        assert t["is_sunny"] is False


def test_list_terraces_filter_sunny_14h(client):
    r = client.get(f"{BASE_URL}/api/terraces",
                   params={"city": "Nantes", "sun_status": "sunny", "at_time": "14:00"})
    assert r.status_code == 200
    body = r.json()
    for t in body["terraces"]:
        assert t["sun_status"] == "sunny"
        assert t["is_sunny"] is True


def test_list_terraces_filter_type(client):
    r = client.get(f"{BASE_URL}/api/terraces",
                   params={"city": "Nantes", "type": "cafe"})
    assert r.status_code == 200
    body = r.json()
    assert body["count"] > 0
    for t in body["terraces"]:
        assert t["type"] == "cafe"


def test_list_terraces_radius_filter(client):
    r = client.get(f"{BASE_URL}/api/terraces",
                   params={"city": "Nantes", "lat": 47.2184, "lng": -1.5536,
                           "radius_km": 1})
    assert r.status_code == 200
    body = r.json()
    for t in body["terraces"]:
        assert t["distance_km"] is not None and t["distance_km"] <= 1


# ---- terrace detail ----
@pytest.fixture(scope="module")
def sample_terrace_id(client):
    r = client.get(f"{BASE_URL}/api/terraces", params={"city": "Nantes"})
    return r.json()["terraces"][0]["id"]


def test_terrace_detail(client, sample_terrace_id):
    r = client.get(f"{BASE_URL}/api/terraces/{sample_terrace_id}")
    assert r.status_code == 200
    data = r.json()
    assert "sun_schedule_today" in data
    assert "hourly_forecast" in data
    assert "sunny_hours" in data["sun_schedule_today"]
    assert isinstance(data["hourly_forecast"], list)
    assert len(data["hourly_forecast"]) == 17  # 6h-22h inclusive
    for h in data["hourly_forecast"]:
        assert "hour" in h and "is_sunny" in h
    assert "_id" not in data


def test_terrace_detail_at_time(client, sample_terrace_id):
    r = client.get(f"{BASE_URL}/api/terraces/{sample_terrace_id}",
                   params={"at_time": "14:00"})
    assert r.status_code == 200
    data = r.json()
    assert data["at_time"].startswith(
        __import__("datetime").datetime.now().strftime("%Y-%m-%d")
    ) or "T14:" in data["at_time"]


def test_terrace_detail_404(client):
    r = client.get(f"{BASE_URL}/api/terraces/nonexistent-id")
    assert r.status_code == 404


# ---- sun position / sun-check ----
def test_sun_position(client):
    r = client.get(f"{BASE_URL}/api/sun-position",
                   params={"lat": 47.2184, "lng": -1.5536, "at_time": "14:00"})
    assert r.status_code == 200
    data = r.json()
    assert "position" in data
    pos = data["position"]
    assert "azimuth" in pos and "altitude" in pos
    # At 14h in Nantes, sun should be roughly south (~180°) and above horizon
    assert pos["altitude"] > 10


def test_sun_check_post(client):
    r = client.post(f"{BASE_URL}/api/sun-check", json={
        "lat": 47.2184, "lng": -1.5536,
        "orientation_degrees": 180, "at_time": "14:00",
    })
    assert r.status_code == 200
    data = r.json()
    assert "is_sunny" in data
    assert "sun_azimuth" in data
    # Facing south at 14h → likely sunny
    assert data["is_sunny"] is True


def test_sun_check_missing_fields(client):
    r = client.post(f"{BASE_URL}/api/sun-check", json={"lat": 48.0})
    assert r.status_code == 400


def test_sun_check_night(client):
    r = client.post(f"{BASE_URL}/api/sun-check", json={
        "lat": 47.2184, "lng": -1.5536,
        "orientation_degrees": 180, "at_time": "02:00",
    })
    assert r.status_code == 200
    assert r.json()["is_sunny"] is False


# ---- weather ----
def test_weather_paris(client):
    r = client.get(f"{BASE_URL}/api/weather/Nantes")
    assert r.status_code == 200
    data = r.json()
    assert data["city"] == "Nantes"
    assert "temperature" in data and "weather_label" in data


def test_weather_invalid_city(client):
    r = client.get(f"{BASE_URL}/api/weather/Atlantis")
    assert r.status_code == 404


# ---- AI description ----
def test_generate_description(client, sample_terrace_id):
    r = client.post(
        f"{BASE_URL}/api/terraces/{sample_terrace_id}/generate-description",
        timeout=60,
    )
    assert r.status_code == 200
    data = r.json()
    assert "ai_description" in data and data["ai_description"]
    assert len(data["ai_description"]) > 10
