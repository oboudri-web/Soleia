"""
Soleia - Emergent Google Auth integration for Expo mobile.

Flow :
  1. Mobile app opens https://auth.emergentagent.com/?redirect=<backend>/api/auth/mobile-callback
     in a Chrome Custom Tab / ASWebAuthenticationSession.
  2. User signs in with Google.
  3. Emergent redirects to /api/auth/mobile-callback#session_id=<sid>
  4. Our HTML callback page extracts session_id and redirects to soleia://auth?session_id=<sid>
  5. App captures the deep link, POSTs /api/auth/session with session_id.
  6. Backend calls Emergent /session-data, creates user + session in Mongo, returns session_token.
  7. App stores session_token in AsyncStorage and sends it in Authorization: Bearer header
     for subsequent requests.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Header, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
from pathlib import Path

try:
    from google.oauth2 import id_token as google_id_token
    from google.auth.transport import requests as google_requests
    GOOGLE_AUTH_AVAILABLE = True
except ImportError:  # pragma: no cover - defensive
    GOOGLE_AUTH_AVAILABLE = False

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]

EMERGENT_SESSION_DATA_URL = "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data"
SESSION_TTL_DAYS = 30  # Sessions valid 30 days for mobile convenience

# Google OAuth Web Client ID (obtained from Google Cloud Console).
# The mobile app signs in with its own iOS/Android client IDs, but Google issues
# an ID token with audience = this WEB client ID so the server can verify it.
GOOGLE_WEB_CLIENT_ID = os.environ.get("GOOGLE_WEB_CLIENT_ID", "")
# Additional accepted audiences (ios/android client IDs) — comma-separated.
GOOGLE_ACCEPTED_AUDIENCES = [
    a.strip() for a in os.environ.get("GOOGLE_ACCEPTED_AUDIENCES", "").split(",") if a.strip()
]
# Always include the web client id if set
if GOOGLE_WEB_CLIENT_ID and GOOGLE_WEB_CLIENT_ID not in GOOGLE_ACCEPTED_AUDIENCES:
    GOOGLE_ACCEPTED_AUDIENCES.append(GOOGLE_WEB_CLIENT_ID)

auth_router = APIRouter(prefix="/api/auth")


# =========================
# Models
# =========================
class SessionExchangeRequest(BaseModel):
    session_id: str


class GoogleNativeRequest(BaseModel):
    id_token: str


class FavoritesUpdateRequest(BaseModel):
    favorite_ids: list[str]


class UserPublic(BaseModel):
    user_id: str
    email: str
    name: str
    picture: Optional[str] = None


# =========================
# Helpers
# =========================
async def _require_session(authorization: Optional[str]) -> dict:
    """Validate Bearer token, return session doc. Raise 401 if invalid."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Empty token")
    sess = await db.user_sessions.find_one({"session_token": token}, {"_id": 0})
    if not sess:
        raise HTTPException(status_code=401, detail="Invalid session")

    expires_at = sess.get("expires_at")
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at)
    if expires_at and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at and expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="Session expired")

    return sess


async def _get_user(user_id: str) -> Optional[dict]:
    return await db.users.find_one({"user_id": user_id}, {"_id": 0})


# =========================
# Mobile HTML callback (deep link bridge)
# =========================
@auth_router.get("/mobile-callback", response_class=HTMLResponse)
async def mobile_callback():
    """
    Static page: served at /api/auth/mobile-callback.
    Emergent Auth redirects here with #session_id=<sid>.
    We extract session_id from the fragment and deep-link back into the app
    via scheme soleia://auth?session_id=<sid>.
    """
    html = """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Soleia - Connexion</title>
<style>
  body{background:#000;color:#fff;font-family:-apple-system,Segoe UI,Roboto,Helvetica,sans-serif;
       display:flex;align-items:center;justify-content:center;height:100vh;margin:0;padding:24px;text-align:center}
  .box{max-width:360px}
  h1{font-size:24px;margin:0 0 12px}
  p{color:#999;margin:8px 0}
  a{color:#F5A623;text-decoration:underline}
</style></head>
<body><div class="box">
  <h1>Connexion Soleia</h1>
  <p id="msg">Redirection vers l'application…</p>
  <p><a id="manual" href="#" style="display:none">Ouvrir l'application</a></p>
</div>
<script>
(function(){
  var h = window.location.hash || '';
  var m = h.match(/session_id=([^&]+)/);
  if (!m) {
    document.getElementById('msg').textContent = 'Erreur : session_id manquant.';
    return;
  }
  var sid = m[1];
  var deep = 'soleia://auth?session_id=' + encodeURIComponent(sid);
  var a = document.getElementById('manual');
  a.href = deep; a.style.display = 'inline';
  // Immediate deep link attempt
  window.location.href = deep;
  setTimeout(function(){
    document.getElementById('msg').textContent = 'Si rien ne se passe, touchez le lien ci-dessous.';
  }, 1500);
})();
</script>
</body></html>"""
    return HTMLResponse(content=html)


# =========================
# Exchange session_id for session_token + user info
# =========================
@auth_router.post("/session")
async def exchange_session(req: SessionExchangeRequest):
    """Called by mobile app after receiving session_id via deep link."""
    if not req.session_id or not req.session_id.strip():
        raise HTTPException(status_code=400, detail="session_id required")

    # Call Emergent /session-data
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            resp = await http.get(
                EMERGENT_SESSION_DATA_URL,
                headers={"X-Session-ID": req.session_id},
            )
        if resp.status_code != 200:
            raise HTTPException(status_code=401, detail=f"Emergent rejected session_id ({resp.status_code})")
        data = resp.json()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Emergent auth unreachable: {e}")

    email = (data.get("email") or "").strip().lower()
    name = (data.get("name") or "").strip() or email.split("@")[0]
    picture = data.get("picture")
    upstream_session_token = data.get("session_token")  # we use our own token instead for mobile

    if not email:
        raise HTTPException(status_code=502, detail="Emergent returned no email")

    # Upsert user
    existing = await db.users.find_one({"email": email}, {"_id": 0})
    now = datetime.now(timezone.utc)
    if existing:
        user_id = existing["user_id"]
        await db.users.update_one(
            {"user_id": user_id},
            {"$set": {"name": name, "picture": picture, "last_login_at": now}},
        )
    else:
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        await db.users.insert_one({
            "user_id": user_id,
            "email": email,
            "name": name,
            "picture": picture,
            "favorite_ids": [],
            "created_at": now,
            "last_login_at": now,
        })

    # Issue our own session_token for the mobile app (so we can rotate / revoke)
    session_token = f"stk_{uuid.uuid4().hex}{uuid.uuid4().hex}"
    await db.user_sessions.insert_one({
        "user_id": user_id,
        "session_token": session_token,
        "expires_at": now + timedelta(days=SESSION_TTL_DAYS),
        "created_at": now,
        "upstream_session_token": upstream_session_token,
    })

    user = await _get_user(user_id)
    return {
        "session_token": session_token,
        "user": {
            "user_id": user["user_id"],
            "email": user["email"],
            "name": user["name"],
            "picture": user.get("picture"),
        },
        "favorite_ids": (user or {}).get("favorite_ids") or [],
    }


# =========================
# Google Sign-In NATIVE (preferred mobile flow) — verifies ID token from
# @react-native-google-signin/google-signin. No browser redirect needed.
# =========================
@auth_router.post("/google-native")
async def google_native(req: GoogleNativeRequest):
    """Called by mobile app after native Google Sign-In. Verifies the ID token
    signature with Google's public keys and creates/updates the user + session."""
    if not GOOGLE_AUTH_AVAILABLE:
        raise HTTPException(status_code=500, detail="google-auth lib not installed on backend")
    if not req.id_token or not req.id_token.strip():
        raise HTTPException(status_code=400, detail="id_token required")
    if not GOOGLE_ACCEPTED_AUDIENCES:
        raise HTTPException(
            status_code=500,
            detail="GOOGLE_WEB_CLIENT_ID not configured on backend (set env var GOOGLE_WEB_CLIENT_ID)",
        )

    # Verify token signature + expiration + audience
    try:
        claims = google_id_token.verify_oauth2_token(
            req.id_token.strip(),
            google_requests.Request(),
            audience=None,  # we verify audience manually to support multiple client ids
        )
    except ValueError as e:
        raise HTTPException(status_code=401, detail=f"Invalid Google ID token: {e}")

    # Reject if issued by a non-Google issuer
    iss = claims.get("iss")
    if iss not in ("accounts.google.com", "https://accounts.google.com"):
        raise HTTPException(status_code=401, detail=f"Unexpected issuer: {iss}")

    # Manual audience check (supports iOS + Android + Web client IDs)
    aud = claims.get("aud")
    if aud not in GOOGLE_ACCEPTED_AUDIENCES:
        raise HTTPException(
            status_code=401,
            detail=f"Unexpected audience: {aud} (accepted: {GOOGLE_ACCEPTED_AUDIENCES})",
        )

    email = (claims.get("email") or "").strip().lower()
    name = (claims.get("name") or "").strip() or (email.split("@")[0] if email else "")
    picture = claims.get("picture")
    google_sub = claims.get("sub")

    if not email:
        raise HTTPException(status_code=401, detail="Google token missing email")
    if not claims.get("email_verified"):
        raise HTTPException(status_code=401, detail="Email not verified by Google")

    # Upsert user by email (also record google_sub for future lookups)
    now = datetime.now(timezone.utc)
    existing = await db.users.find_one({"email": email}, {"_id": 0})
    if existing:
        user_id = existing["user_id"]
        await db.users.update_one(
            {"user_id": user_id},
            {"$set": {
                "name": name,
                "picture": picture,
                "google_sub": google_sub,
                "last_login_at": now,
            }},
        )
    else:
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        await db.users.insert_one({
            "user_id": user_id,
            "email": email,
            "name": name,
            "picture": picture,
            "google_sub": google_sub,
            "favorite_ids": [],
            "created_at": now,
            "last_login_at": now,
        })

    # Issue our own session token (we do NOT store the Google ID token; it's short-lived)
    session_token = f"stk_{uuid.uuid4().hex}{uuid.uuid4().hex}"
    await db.user_sessions.insert_one({
        "user_id": user_id,
        "session_token": session_token,
        "expires_at": now + timedelta(days=SESSION_TTL_DAYS),
        "created_at": now,
        "auth_provider": "google_native",
    })

    user = await _get_user(user_id)
    return {
        "session_token": session_token,
        "user": {
            "user_id": user["user_id"],
            "email": user["email"],
            "name": user["name"],
            "picture": user.get("picture"),
        },
        "favorite_ids": (user or {}).get("favorite_ids") or [],
    }


# =========================
# Current user
# =========================
@auth_router.get("/me")
async def me(authorization: Optional[str] = Header(None)):
    sess = await _require_session(authorization)
    user = await _get_user(sess["user_id"])
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {
        "user_id": user["user_id"],
        "email": user["email"],
        "name": user["name"],
        "picture": user.get("picture"),
        "favorite_ids": user.get("favorite_ids") or [],
    }


# =========================
# Logout
# =========================
@auth_router.post("/logout")
async def logout(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.lower().startswith("bearer "):
        return {"ok": True}
    token = authorization.split(" ", 1)[1].strip()
    if token:
        await db.user_sessions.delete_one({"session_token": token})
    return {"ok": True}


# =========================
# Favorites: get / put
# =========================
@auth_router.get("/favorites")
async def get_favorites(authorization: Optional[str] = Header(None)):
    sess = await _require_session(authorization)
    user = await _get_user(sess["user_id"])
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"favorite_ids": user.get("favorite_ids") or []}


@auth_router.put("/favorites")
async def put_favorites(req: FavoritesUpdateRequest, authorization: Optional[str] = Header(None)):
    sess = await _require_session(authorization)
    fav_ids = [fid for fid in (req.favorite_ids or []) if isinstance(fid, str) and fid][:500]
    # Preserve order, dedupe
    seen = set()
    deduped: list[str] = []
    for fid in fav_ids:
        if fid in seen:
            continue
        seen.add(fid)
        deduped.append(fid)
    await db.users.update_one(
        {"user_id": sess["user_id"]},
        {"$set": {"favorite_ids": deduped, "favorites_updated_at": datetime.now(timezone.utc)}},
    )
    return {"ok": True, "favorite_ids": deduped}


@auth_router.post("/favorites/merge")
async def merge_favorites(req: FavoritesUpdateRequest, authorization: Optional[str] = Header(None)):
    """Merge local AsyncStorage favorites with server favorites (used on first login).
    Union, preserve order (server first, then new locals)."""
    sess = await _require_session(authorization)
    user = await _get_user(sess["user_id"])
    server_ids: list[str] = (user or {}).get("favorite_ids") or []
    local_ids = [fid for fid in (req.favorite_ids or []) if isinstance(fid, str) and fid]
    seen = set(server_ids)
    merged = list(server_ids)
    for fid in local_ids:
        if fid in seen:
            continue
        seen.add(fid)
        merged.append(fid)
    merged = merged[:500]
    await db.users.update_one(
        {"user_id": sess["user_id"]},
        {"$set": {"favorite_ids": merged, "favorites_updated_at": datetime.now(timezone.utc)}},
    )
    return {"ok": True, "favorite_ids": merged, "added": len(merged) - len(server_ids)}
