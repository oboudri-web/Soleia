#!/usr/bin/env bash
# Soleia - Quick overnight progress check
# Usage: bash /app/backend/scripts/check_overnight.sh

echo "=== Overnight batch status — $(date -Is) ==="
echo ""

echo "### Processes still running ###"
ps aux | grep -E "qualify_(shadows|terraces)" | grep -v grep || echo "  (no active batch processes — all done)"
echo ""

echo "### Shadow batch tail ###"
tail -n 20 /tmp/overnight_shadow.log 2>/dev/null || echo "  (no log yet)"
echo ""

echo "### Vision batch tail ###"
tail -n 20 /tmp/overnight_vision.log 2>/dev/null || echo "  (no log yet)"
echo ""

echo "### Status markers ###"
cat /tmp/overnight_status.log 2>/dev/null || echo "  (no completion markers yet)"
echo ""

echo "### DB counts (confirmed per city) ###"
cd /app/backend
python3 -c "
import asyncio, os
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
load_dotenv('/app/backend/.env')
async def go():
    c = AsyncIOMotorClient(os.environ['MONGO_URL'])
    db = c[os.environ.get('DB_NAME','soleia')]
    pipe = [{'\$match': {'has_terrace_confirmed': True}},
            {'\$group': {'_id': '\$city', 'count': {'\$sum': 1}, 'analyzed': {'\$sum': {'\$cond': ['\$has_shadow_analysis', 1, 0]}}}},
            {'\$sort': {'count': -1}}]
    async for d in db.terraces.aggregate(pipe):
        a = d.get('analyzed', 0)
        print(f\"  {d['_id']:15s}  {d['count']:5d} confirmed   {a:5d} shadow-analyzed\")
asyncio.run(go())
"
