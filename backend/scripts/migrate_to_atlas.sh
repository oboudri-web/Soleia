#!/usr/bin/env bash
# Soleia — migration MongoDB Emergent preview -> MongoDB Atlas (production)
#
# Usage:
#   1. Renseigner les 2 variables ci-dessous :
#        SOURCE_URI : URI Mongo dans le container Emergent (cf backend/.env)
#        TARGET_URI : URI Atlas mongodb+srv://...
#   2. chmod +x backend/scripts/migrate_to_atlas.sh
#   3. ./backend/scripts/migrate_to_atlas.sh
#
# Ce script :
#   1. Dump toutes les collections de la base source vers /tmp/soleia_dump
#   2. Restore le dump dans la base "soleia" sur Atlas
#   3. Affiche un récapitulatif des collections + counts
#
# Pré-requis local : `mongodump` + `mongorestore` installés (paquet
# mongodb-database-tools). Sur Mac : `brew install mongodb-database-tools`.
# Sur Linux : https://www.mongodb.com/try/download/database-tools

set -euo pipefail

# ─────────────────────────────────────────────────────────────────────────
# A REMPLIR
# ─────────────────────────────────────────────────────────────────────────
SOURCE_URI="${SOURCE_URI:-mongodb://localhost:27017}"
SOURCE_DB="${SOURCE_DB:-suntterrace_db}"

TARGET_URI="${TARGET_URI:-MUST_FILL_mongodb+srv://USER:PASS@cluster0.xxxxx.mongodb.net}"
TARGET_DB="${TARGET_DB:-soleia}"

DUMP_DIR="${DUMP_DIR:-/tmp/soleia_dump}"

if [[ "$TARGET_URI" == MUST_FILL* ]]; then
  echo "❌ TARGET_URI non configurée. Editez ce script ou exportez la var d'env."
  echo "   Exemple : export TARGET_URI='mongodb+srv://u:p@cluster0.xxx.mongodb.net'"
  exit 1
fi

echo "━━━ 1/3 — Dump de $SOURCE_DB depuis Emergent..."
rm -rf "$DUMP_DIR"
mkdir -p "$DUMP_DIR"
mongodump --uri="$SOURCE_URI" --db="$SOURCE_DB" --out="$DUMP_DIR"
echo "  ✓ Dump terminé : $DUMP_DIR/$SOURCE_DB/"
ls -lh "$DUMP_DIR/$SOURCE_DB/" || true

echo ""
echo "━━━ 2/3 — Restore vers MongoDB Atlas (DB=$TARGET_DB)..."
mongorestore --uri="$TARGET_URI" \
  --nsFrom="$SOURCE_DB.*" --nsTo="$TARGET_DB.*" \
  "$DUMP_DIR"
echo "  ✓ Restore terminé"

echo ""
echo "━━━ 3/3 — Vérification counts par collection..."
python3 - <<EOF
import os, sys
from pymongo import MongoClient
uri = "$TARGET_URI"
db_name = "$TARGET_DB"
try:
    client = MongoClient(uri, serverSelectionTimeoutMS=8000)
    db = client[db_name]
    print(f"  Atlas DB={db_name}")
    for c in sorted(db.list_collection_names()):
        n = db[c].estimated_document_count()
        print(f"    {c:30s} {n:>8,} docs")
except Exception as e:
    print(f"  ⚠️  Vérification impossible : {e}")
    sys.exit(0)
EOF

echo ""
echo "✅ Migration complète. Mettez à jour MONGO_URL / DB_NAME côté Render."
