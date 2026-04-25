#!/bin/bash
# Soleia - Overnight pipeline 3 (April 2026)
#  - Shadows OSM pour Bordeaux / Toulouse / Nice / Montpellier (séquentiel, ~4s/terrasse)
#  - Google Places Details pour Paris / Nice / Montpellier (parallèle Google)
#  - Re-qualification permissive Nantes (Claude Vision, permissif)
set -u
cd /app/backend

LOG_DIR=/tmp
STAMP=$(date +%Y%m%d_%H%M%S)

echo "=== OVERNIGHT 3 — start $(date -Iseconds) ===" | tee -a $LOG_DIR/overnight3_status.log

# 1) Google Places Details (cheap, can run first, parallel with shadows)
{
  echo "[details] start $(date -Iseconds)"
  python3 scripts/enrich_details.py --city Paris Nice Montpellier 2>&1
  echo "[details] done $(date -Iseconds)"
} > $LOG_DIR/overnight3_details.log 2>&1 &
PID_DETAILS=$!
echo "details PID=$PID_DETAILS" | tee -a $LOG_DIR/overnight3_status.log

# 2) Nantes re-qualification permissive (Claude Vision, ~$9 for 730)
{
  echo "[nantes] start $(date -Iseconds)"
  python3 scripts/requalify_nantes_permissive.py 2>&1
  echo "[nantes] done $(date -Iseconds)"
} > $LOG_DIR/overnight3_nantes.log 2>&1 &
PID_NANTES=$!
echo "nantes PID=$PID_NANTES" | tee -a $LOG_DIR/overnight3_status.log

# 3) Shadows (séquentiel pour rester gentil avec Overpass)
{
  echo "[shadows] start $(date -Iseconds)"
  for city in Bordeaux Toulouse Nice Montpellier; do
    echo "[shadows] --- $city ---"
    python3 scripts/qualify_shadows_nantes.py --city "$city" 2>&1
    echo "[shadows] --- $city done at $(date -Iseconds) ---"
  done
  echo "[shadows] done $(date -Iseconds)"
} > $LOG_DIR/overnight3_shadows.log 2>&1 &
PID_SHADOWS=$!
echo "shadows PID=$PID_SHADOWS" | tee -a $LOG_DIR/overnight3_status.log

echo "All 3 batches launched. PIDs: details=$PID_DETAILS nantes=$PID_NANTES shadows=$PID_SHADOWS"
echo "Tail logs in $LOG_DIR/overnight3_*.log"
