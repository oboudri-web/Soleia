#!/bin/bash
# Soleia - Overnight SHADOWS ALL : Shadow Engine 3D OSM sur toutes les villes pas encore traitées
# Séquence : Marseille → Bordeaux → Toulouse → Nice → Montpellier → Lyon → Paris (l'ordre du user)
# Pacing 4s + retries Overpass déjà dans shadow_engine.py (3 miroirs, backoff)
# Idempotent : skip terrasses has_shadow_analysis=true
# ~1051 terrasses total à traiter ≈ 70 minutes

set -u
cd /app/backend

LOG=/tmp/overnight_shadows_all.log
STATUS=/tmp/overnight_shadows_status.log

: > $LOG
: > $STATUS

echo "=== OVERNIGHT SHADOWS ALL START $(date -Iseconds) ===" | tee -a $STATUS $LOG

# Snapshot initial
python3 - << 'PY' | tee -a $STATUS $LOG
import asyncio, os
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
async def m():
    c = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = c[os.environ["DB_NAME"]]
    for city in ["Marseille","Bordeaux","Toulouse","Nice","Montpellier","Lyon","Paris","Nantes"]:
        need = await db.terraces.count_documents({
            "city": city,
            "$or": [
                {"has_terrace_confirmed": True},
                {"has_terrace_confirmed": {"$exists": False}},
            ],
            "has_shadow_analysis": {"$ne": True},
        })
        done = await db.terraces.count_documents({"city": city, "has_shadow_analysis": True})
        print(f"[PRE] {city}: shadow_done={done}, shadow_need={need}")
asyncio.run(m())
PY

# Ordre demandé par l'utilisateur
CITIES=("Marseille" "Bordeaux" "Toulouse" "Nice" "Montpellier" "Lyon" "Paris")

for city in "${CITIES[@]}"; do
    echo "" | tee -a $LOG
    echo "################################################################" | tee -a $LOG
    echo "### [${city}] SHADOW qualification START $(date -Iseconds) ###" | tee -a $STATUS $LOG
    echo "################################################################" | tee -a $LOG
    python3 scripts/qualify_shadows_nantes.py --city "$city" >> $LOG 2>&1
    EXIT=$?
    echo "### [${city}] SHADOW DONE exit=$EXIT $(date -Iseconds) ###" | tee -a $STATUS $LOG
    # Small cool-down entre villes pour Overpass
    sleep 10
done

# Snapshot final
echo "" | tee -a $LOG
python3 - << 'PY' | tee -a $STATUS $LOG
import asyncio, os
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
async def m():
    c = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = c[os.environ["DB_NAME"]]
    total_done, total_need = 0, 0
    for city in ["Paris","Lyon","Marseille","Bordeaux","Nantes","Toulouse","Nice","Montpellier"]:
        need = await db.terraces.count_documents({
            "city": city,
            "$or": [
                {"has_terrace_confirmed": True},
                {"has_terrace_confirmed": {"$exists": False}},
            ],
            "has_shadow_analysis": {"$ne": True},
        })
        done = await db.terraces.count_documents({"city": city, "has_shadow_analysis": True})
        total_done += done; total_need += need
        print(f"[FINAL] {city}: shadow_done={done}, remaining={need}")
    print(f"[FINAL TOTAL] shadow_done={total_done}, remaining={total_need}")
asyncio.run(m())
PY

echo "=== OVERNIGHT SHADOWS ALL FINISHED $(date -Iseconds) ===" | tee -a $STATUS $LOG
