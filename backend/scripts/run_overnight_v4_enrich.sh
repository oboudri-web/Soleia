#!/bin/bash
# Soleia - Enrichissement Google Places Details (overnight #4, avril 2026)
# - Priorité : Paris, Nice, Montpellier
# - Ensuite : Lyon, Marseille, Bordeaux, Nantes, Toulouse
# - ~5685 calls au total @ $0.017 ≈ $96
# - Idempotent (skip details_enriched_at présent)

set -u
cd /app/backend

LOG_DIR=/tmp
STAMP=$(date +%Y%m%d_%H%M%S)
MAIN_LOG=$LOG_DIR/overnight4_enrich.log
STATUS=$LOG_DIR/overnight4_status.log

echo "=== OVERNIGHT #4 ENRICH START $(date -Iseconds) ===" | tee -a $STATUS

# 1) Priority batch : Paris / Nice / Montpellier
echo "[prio] start $(date -Iseconds)" | tee -a $STATUS
{
  echo ">>> ENRICH PRIORITY: Paris Nice Montpellier <<<"
  python3 scripts/enrich_details.py --city Paris Nice Montpellier
  echo ">>> PRIORITY DONE $(date -Iseconds) <<<"
  echo ""

  # 2) Secondary : Lyon Marseille Bordeaux Nantes Toulouse
  echo ">>> ENRICH SECONDARY: Lyon Marseille Bordeaux Nantes Toulouse <<<"
  python3 scripts/enrich_details.py --city Lyon Marseille Bordeaux Nantes Toulouse
  echo ">>> SECONDARY DONE $(date -Iseconds) <<<"
} > $MAIN_LOG 2>&1

echo "=== OVERNIGHT #4 ENRICH FINISHED $(date -Iseconds) ===" | tee -a $STATUS
