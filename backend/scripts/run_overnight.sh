#!/bin/bash
# Soleia - Pipeline overnight: dense seed + qualify
# Run:
#   nohup bash /app/backend/scripts/run_overnight.sh > /tmp/overnight.log 2>&1 &

set -u
cd /app/backend

START=$(date +%s)
echo "=== [$(date)] START overnight pipeline ==="

echo ""
echo "--- [1/2] DENSE SEED Google Places (49 zones/ville x 11 villes) ---"
python scripts/seed_google_places.py
SEED_STATUS=$?
echo "--- seed exit=$SEED_STATUS at $(date) ---"

if [ "$SEED_STATUS" -ne 0 ]; then
    echo "SEED FAILED, still launching qualify on existing data."
fi

echo ""
echo "--- [2/2] QUALIFICATION Street View + Claude Vision (EMERGENT_LLM_KEY) ---"
python scripts/qualify_terraces.py
QUALIFY_STATUS=$?
echo "--- qualify exit=$QUALIFY_STATUS at $(date) ---"

END=$(date +%s)
ELAPSED=$(( (END - START) / 60 ))
echo ""
echo "=== [$(date)] DONE overnight pipeline (${ELAPSED} min) ==="
