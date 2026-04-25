#!/bin/bash
# Soleia - Overnight OSM SHADOWS : process all new terrace_source=osm docs
# Wait for existing Paris shadow batch to finish, then process OSM docs across 8 cities.
# ~6195 OSM docs × 4s = ~7 hours total.

set -u
cd /app/backend

LOG=/tmp/overnight_shadows_osm.log
STATUS=/tmp/overnight_shadows_osm_status.log

: > $LOG
: > $STATUS

echo "=== OVERNIGHT OSM SHADOWS START $(date -Iseconds) ===" | tee -a $STATUS $LOG

# Wait for any current qualify_shadows process to finish (max 45 min)
echo "[wait] Waiting for any current qualify_shadows process..." | tee -a $STATUS
WAIT_SECS=0
while pgrep -f "qualify_shadows_nantes.py" > /dev/null 2>&1; do
    if [ $WAIT_SECS -ge 2700 ]; then
        echo "[wait] Timeout after 45 min, proceeding anyway" | tee -a $STATUS
        break
    fi
    sleep 30
    WAIT_SECS=$((WAIT_SECS + 30))
    if [ $((WAIT_SECS % 300)) -eq 0 ]; then
        echo "[wait] Still waiting... ${WAIT_SECS}s elapsed" | tee -a $STATUS
    fi
done
echo "[wait] Paris shadow batch finished after ${WAIT_SECS}s wait" | tee -a $STATUS

# Snapshot initial
python3 - << 'PY' | tee -a $STATUS $LOG
import asyncio, os
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
async def m():
    c = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = c[os.environ["DB_NAME"]]
    tot_need = 0
    for city in ["Paris","Lyon","Marseille","Bordeaux","Nantes","Toulouse","Nice","Montpellier"]:
        need = await db.terraces.count_documents({
            "city": city, "terrace_source": "osm",
            "has_shadow_analysis": {"$ne": True}
        })
        tot_need += need
        print(f"[PRE] {city}: OSM docs needing shadow = {need}")
    print(f"[PRE TOTAL] {tot_need} OSM docs to process @ 4s = {tot_need*4//60} minutes")
asyncio.run(m())
PY

# Process in this order : cities with fewer OSM docs first (faster feedback),
# Paris last (biggest: 3545 docs)
CITIES=("Nice" "Nantes" "Montpellier" "Toulouse" "Bordeaux" "Marseille" "Lyon" "Paris")

for city in "${CITIES[@]}"; do
    echo "" | tee -a $LOG
    echo "################################################################" | tee -a $LOG
    echo "### [${city}] OSM SHADOW START $(date -Iseconds) ###" | tee -a $STATUS $LOG
    echo "################################################################" | tee -a $LOG
    python3 scripts/qualify_shadows_nantes.py --city "$city" --osm-only >> $LOG 2>&1
    EXIT=$?
    echo "### [${city}] OSM SHADOW DONE exit=$EXIT $(date -Iseconds) ###" | tee -a $STATUS $LOG
    # 15s cool-down between cities for Overpass mirrors
    sleep 15
done

# Final snapshot
echo "" | tee -a $LOG
python3 - << 'PY' | tee -a $STATUS $LOG
import asyncio, os
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
async def m():
    c = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = c[os.environ["DB_NAME"]]
    for city in ["Paris","Lyon","Marseille","Bordeaux","Nantes","Toulouse","Nice","Montpellier"]:
        total_osm = await db.terraces.count_documents({"city": city, "terrace_source": "osm"})
        done_osm = await db.terraces.count_documents({"city": city, "terrace_source": "osm", "has_shadow_analysis": True})
        print(f"[FINAL] {city}: OSM shadow done {done_osm}/{total_osm}")
asyncio.run(m())
PY

echo "=== OVERNIGHT OSM SHADOWS FINISHED $(date -Iseconds) ===" | tee -a $STATUS $LOG
