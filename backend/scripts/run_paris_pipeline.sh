#!/usr/bin/env bash
# Soleia - Paris full pipeline (overnight)
# Runs 3 steps sequentially:
#   1. Dense Google Places seed (Paris only, 13x13 = 169 zones, 300m step)
#   2. Claude Vision qualification (Paris only)
#   3. Shadow engine 3D (Paris only)
#
# Preserves existing manual/street_view_ai+confirmed Paris terraces (seed script handles this).
# Logs: /tmp/paris_pipeline.log + /tmp/paris_pipeline_status.log

cd /app/backend
: > /tmp/paris_pipeline.log
: > /tmp/paris_pipeline_status.log

(
  {
    echo "========================================================="
    echo "=== Soleia Paris Pipeline — START $(date -Is)"
    echo "========================================================="
    echo ""

    echo "### STEP 1/3 — Dense Google Places seed on Paris (13x13 zones)"
    echo "$(date -Is) START SEED"
    python3 scripts/seed_google_places.py --city Paris --grid 13 --step 300
    rc=$?
    echo "$(date -Is) END SEED (rc=$rc)"
    echo "STEP_1_SEED_DONE $(date -Is) rc=$rc" >> /tmp/paris_pipeline_status.log
    if [ $rc -ne 0 ]; then
      echo "SEED failed — abort pipeline."
      exit $rc
    fi

    echo ""
    echo "### STEP 2/3 — Claude Vision qualification on Paris"
    echo "$(date -Is) START VISION"
    python3 scripts/qualify_terraces.py --city Paris
    rc=$?
    echo "$(date -Is) END VISION (rc=$rc)"
    echo "STEP_2_VISION_DONE $(date -Is) rc=$rc" >> /tmp/paris_pipeline_status.log
    if [ $rc -ne 0 ]; then
      echo "VISION failed — abort shadow step."
      exit $rc
    fi

    echo ""
    echo "### STEP 3/3 — Shadow engine 3D on Paris"
    echo "$(date -Is) START SHADOW"
    python3 scripts/qualify_shadows_nantes.py --city Paris
    rc=$?
    echo "$(date -Is) END SHADOW (rc=$rc)"
    echo "STEP_3_SHADOW_DONE $(date -Is) rc=$rc" >> /tmp/paris_pipeline_status.log

    echo ""
    echo "========================================================="
    echo "=== Soleia Paris Pipeline — END $(date -Is)"
    echo "========================================================="
    echo "PIPELINE_DONE $(date -Is)" >> /tmp/paris_pipeline_status.log
  } >> /tmp/paris_pipeline.log 2>&1
) &
PARIS_PID=$!
disown $PARIS_PID 2>/dev/null || true

echo "Paris pipeline PID: $PARIS_PID → /tmp/paris_pipeline.log"
echo "Status markers:     /tmp/paris_pipeline_status.log"
