#!/usr/bin/env bash
# Soleia - Overnight batch launcher
# Runs two jobs in parallel, both detached from parent shell (setsid).
#  1. Shadow engine (OSM ray-cast) for Paris, Lyon, Marseille, Bordeaux
#  2. Claude Vision qualification for Toulouse, Nice, Montpellier
#
# Usage:  bash /app/backend/scripts/run_overnight_v2.sh
# Logs:   /tmp/overnight_shadow.log  /tmp/overnight_vision.log

cd /app/backend
: > /tmp/overnight_shadow.log
: > /tmp/overnight_vision.log
: > /tmp/overnight_status.log

# ---- JOB 1: Shadow batch (4 cities sequentially) --------------------------
(
  {
    echo "=== START SHADOW $(date -Is) ==="
    for city in Paris Lyon Marseille Bordeaux; do
      echo ""
      echo "### $city $(date -Is) ###"
      python3 scripts/qualify_shadows_nantes.py --city "$city"
    done
    echo ""
    echo "=== END SHADOW $(date -Is) ==="
  } >> /tmp/overnight_shadow.log 2>&1
  echo "SHADOW_DONE $(date -Is)" >> /tmp/overnight_status.log
) &
SHADOW_PID=$!
disown $SHADOW_PID 2>/dev/null || true

# ---- JOB 2: Claude Vision qualification (Toulouse + Nice + Montpellier) ---
(
  {
    echo "=== START VISION $(date -Is) ==="
    python3 scripts/qualify_terraces.py
    echo "=== END VISION $(date -Is) ==="
  } >> /tmp/overnight_vision.log 2>&1
  echo "VISION_DONE $(date -Is)" >> /tmp/overnight_status.log
) &
VISION_PID=$!
disown $VISION_PID 2>/dev/null || true

echo "Shadow batch PID:  $SHADOW_PID → /tmp/overnight_shadow.log"
echo "Vision batch PID:  $VISION_PID → /tmp/overnight_vision.log"
echo "Status marker:      /tmp/overnight_status.log"
