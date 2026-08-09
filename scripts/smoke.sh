#!/usr/bin/env bash
# End-to-end smoke test of a running TriggersAPI.
#
#   bash scripts/smoke.sh https://your-app.up.railway.app
#   bash scripts/smoke.sh                      # defaults to http://localhost:8000
#
# Exercises the whole public contract with the published demo keys:
# health, idempotent ingest, the anti-join inbox (marks read), /last neutrality,
# cross-tenant isolation, and auth. Pretty-prints JSON if `jq` is installed.
set -u

BASE="${1:-http://localhost:8000}"
KEY_A="${KEY_A:-demo-key-a}"
KEY_B="${KEY_B:-demo-key-b}"
EID="evt-$(date +%s)"   # unique per run, so the script is re-runnable on camera

if command -v jq >/dev/null 2>&1; then PP="jq ."; else PP="cat"; fi

hr() { printf '\n\033[1m%s\033[0m\n' "$*"; }

hr "① health  ->  expect {\"status\":\"ok\"}"
curl -s "$BASE/healthz" | $PP

hr "② produce  ->  expect HTTP 201, deduped:false"
curl -s -w '   [HTTP %{http_code}]\n' -X POST "$BASE/v1/events" \
  -H "Authorization: Bearer $KEY_A" -H "Content-Type: application/json" \
  -d "{\"event_id\":\"$EID\",\"event_type\":\"order.created\",\"payload\":{\"order_id\":9931}}"

hr "③ replay the SAME event_id  ->  idempotent: expect HTTP 200, deduped:true"
curl -s -w '   [HTTP %{http_code}]\n' -X POST "$BASE/v1/events" \
  -H "Authorization: Bearer $KEY_A" -H "Content-Type: application/json" \
  -d "{\"event_id\":\"$EID\",\"event_type\":\"order.created\",\"payload\":{\"order_id\":9931}}"

hr "④ inbox  ->  returns the event and marks it read; unread_remaining:0"
curl -s "$BASE/v1/inbox" -H "Authorization: Bearer $KEY_A" | $PP

hr "⑤ inbox again  ->  now empty (already delivered)"
curl -s "$BASE/v1/inbox" -H "Authorization: Bearer $KEY_A" | $PP

hr "⑥ /last peek  ->  still shows it; does NOT mark read"
curl -s "$BASE/v1/last?num=5" -H "Authorization: Bearer $KEY_A" | $PP

hr "⑦ isolation  ->  cust_b's key sees none of cust_a's events"
curl -s "$BASE/v1/inbox" -H "Authorization: Bearer $KEY_B" | $PP

hr "⑧ auth  ->  no key returns HTTP 401"
curl -s -o /dev/null -w '   [HTTP %{http_code}]\n' "$BASE/v1/inbox"

hr "done ✅  (interactive API docs: $BASE/docs)"
