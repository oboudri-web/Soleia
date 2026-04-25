#!/bin/bash
# Soleia - Overnight #5 : Dense UPSERT seed + enrich (Paris first, Lyon fallback if budget allows)
# Budget cible : $70 Google Places API
#   - Paris 15x15 = 225 zones @ 200m ≈ $7.20 searchNearby + ~$45 enrich (≈$53 total)
#   - Lyon  10x10 = 100 zones @ 300m ≈ $3.20 searchNearby + ~$13 enrich (≈$16 total)
# Mode UPSERT strict : zero DELETE, preserve tous les enrichments (details_enriched_at, phone, hours, etc.)
# Enrich idempotent : skip les docs avec details_enriched_at déjà présent

set -u
cd /app/backend

LOG_DIR=/tmp
STAMP=$(date +%Y%m%d_%H%M%S)
MAIN_LOG=$LOG_DIR/overnight5_main.log
STATUS=$LOG_DIR/overnight5_status.log
PARIS_LOG=$LOG_DIR/overnight5_paris_seed.log
PARIS_ENRICH_LOG=$LOG_DIR/overnight5_paris_enrich.log
LYON_LOG=$LOG_DIR/overnight5_lyon_seed.log
LYON_ENRICH_LOG=$LOG_DIR/overnight5_lyon_enrich.log

echo "=== OVERNIGHT #5 START $(date -Iseconds) ===" | tee -a $STATUS

# Snapshot counts before
python3 - << 'PY' | tee -a $STATUS
import asyncio, os
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
async def m():
    c = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = c[os.environ["DB_NAME"]]
    for city in ["Paris", "Lyon"]:
        t = await db.terraces.count_documents({"city": city})
        e = await db.terraces.count_documents({"city": city, "details_enriched_at": {"$exists": True}})
        print(f"[SNAPSHOT PRE] {city}: total={t}, enriched={e}")
asyncio.run(m())
PY

# =============================================================
# PHASE 1 : PARIS SEED (UPSERT) 15x15 = 225 zones @ 200m
# =============================================================
echo "[phase 1] PARIS SEED UPSERT start $(date -Iseconds)" | tee -a $STATUS
python3 scripts/seed_google_places.py --city Paris --grid 15 --step 200 --upsert > $PARIS_LOG 2>&1
PARIS_SEED_EXIT=$?
echo "[phase 1] PARIS SEED UPSERT done exit=$PARIS_SEED_EXIT $(date -Iseconds)" | tee -a $STATUS

# Snapshot intermediate
python3 - << 'PY' | tee -a $STATUS
import asyncio, os
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
async def m():
    c = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = c[os.environ["DB_NAME"]]
    t = await db.terraces.count_documents({"city": "Paris"})
    e = await db.terraces.count_documents({"city": "Paris", "details_enriched_at": {"$exists": True}})
    ne = await db.terraces.count_documents({"city": "Paris", "details_enriched_at": {"$exists": False}})
    print(f"[SNAPSHOT POST-SEED PARIS] total={t}, enriched={e}, NEW_to_enrich={ne}")
asyncio.run(m())
PY

# =============================================================
# PHASE 2 : PARIS ENRICH (idempotent, n'enrichit que les nouveaux)
# =============================================================
echo "[phase 2] PARIS ENRICH start $(date -Iseconds)" | tee -a $STATUS
python3 scripts/enrich_details.py --city Paris > $PARIS_ENRICH_LOG 2>&1
PARIS_ENRICH_EXIT=$?
echo "[phase 2] PARIS ENRICH done exit=$PARIS_ENRICH_EXIT $(date -Iseconds)" | tee -a $STATUS

# Snapshot after Paris enrich
python3 - << 'PY' | tee -a $STATUS
import asyncio, os
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
async def m():
    c = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = c[os.environ["DB_NAME"]]
    t = await db.terraces.count_documents({"city": "Paris"})
    e = await db.terraces.count_documents({"city": "Paris", "details_enriched_at": {"$exists": True}})
    ph = await db.terraces.count_documents({"city": "Paris", "phone_number": {"$ne": None, "$exists": True}})
    w = await db.terraces.count_documents({"city": "Paris", "website_uri": {"$ne": None, "$exists": True}})
    h = await db.terraces.count_documents({"city": "Paris", "opening_hours": {"$ne": None, "$exists": True}})
    print(f"[SNAPSHOT POST-ENRICH PARIS] total={t}, enriched={e} ({e*100//max(t,1)}%), phone={ph}, web={w}, hours={h}")
asyncio.run(m())
PY

# =============================================================
# PHASE 3 : LYON SEED (UPSERT) 10x10 = 100 zones @ 300m (fallback if budget allows)
# =============================================================
echo "[phase 3] LYON SEED UPSERT start $(date -Iseconds)" | tee -a $STATUS
python3 scripts/seed_google_places.py --city Lyon --grid 10 --step 300 --upsert > $LYON_LOG 2>&1
LYON_SEED_EXIT=$?
echo "[phase 3] LYON SEED UPSERT done exit=$LYON_SEED_EXIT $(date -Iseconds)" | tee -a $STATUS

# =============================================================
# PHASE 4 : LYON ENRICH
# =============================================================
echo "[phase 4] LYON ENRICH start $(date -Iseconds)" | tee -a $STATUS
python3 scripts/enrich_details.py --city Lyon > $LYON_ENRICH_LOG 2>&1
LYON_ENRICH_EXIT=$?
echo "[phase 4] LYON ENRICH done exit=$LYON_ENRICH_EXIT $(date -Iseconds)" | tee -a $STATUS

# Final snapshot
python3 - << 'PY' | tee -a $STATUS
import asyncio, os
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
async def m():
    c = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = c[os.environ["DB_NAME"]]
    for city in ["Paris","Lyon","Marseille","Bordeaux","Nantes","Toulouse","Nice","Montpellier"]:
        t = await db.terraces.count_documents({"city": city})
        e = await db.terraces.count_documents({"city": city, "details_enriched_at": {"$exists": True}})
        print(f"[SNAPSHOT FINAL] {city}: total={t}, enriched={e} ({e*100//max(t,1)}%)")
asyncio.run(m())
PY

echo "=== OVERNIGHT #5 FINISHED $(date -Iseconds) ===" | tee -a $STATUS
