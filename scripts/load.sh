#!/usr/bin/env bash
# Produce N events, then verify every one by id via GET /v1/events/{id}.
#
#   bash scripts/load.sh https://your-app.up.railway.app 20
#   bash scripts/load.sh                       # localhost:8000, N=20
#   KEY=demo-key-b bash scripts/load.sh <url> 50
set -u

BASE="${1:-http://localhost:8000}"
N="${2:-20}"
KEY="${KEY:-demo-key-a}"
RUN="run-$(date +%s)"          # unique prefix so ids don't collide across runs

echo "Producing $N events as key '$KEY' -> $BASE  (id prefix: $RUN)"

produced=0
for i in $(seq 1 "$N"); do
  eid="$RUN-$i"
  code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/v1/events" \
    -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
    -d "{\"event_id\":\"$eid\",\"event_type\":\"load.test\",\"payload\":{\"n\":$i}}")
  # 201 new or 200 deduped both count as stored
  if [ "$code" = "201" ] || [ "$code" = "200" ]; then produced=$((produced+1)); fi
done
echo "  stored: $produced/$N"

echo "Verifying each by id via GET /v1/events/{id}"
verified=0
missing=""
for i in $(seq 1 "$N"); do
  eid="$RUN-$i"
  code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/v1/events/$eid" \
    -H "Authorization: Bearer $KEY")
  if [ "$code" = "200" ]; then verified=$((verified+1)); else missing="$missing $eid($code)"; fi
done
echo "  verified: $verified/$N"
[ -n "$missing" ] && echo "  MISSING:$missing"

if [ "$produced" = "$N" ] && [ "$verified" = "$N" ]; then
  echo "OK ✅  $N produced and all $N confirmed by id"
else
  echo "FAIL ❌  produced=$produced verified=$verified (expected $N)"
  exit 1
fi
