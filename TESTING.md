# Testing a running TriggersAPI

Point these at your deployment's base URL (e.g. the Railway domain). The demo
keys `demo-key-a` / `demo-key-b` are seeded on boot — no signup needed.

## Option A — one command (best for a demo/recording)

```bash
bash scripts/smoke.sh https://<your-app>.up.railway.app
```

Runs the full contract with labeled steps: health → idempotent ingest → inbox
(marks read) → inbox-again (empty) → `/last` peek → cross-tenant isolation →
auth 401. Pretty-prints with `jq` if you have it. Re-runnable (each run uses a
fresh `event_id`).

## Option B — interactive API docs (nice visuals)

Open in a browser:

```
https://<your-app>.up.railway.app/docs
```

1. **Authorize** → enter `demo-key-a`.
2. **POST /v1/events** → *Try it out* → *Execute* → `201`.
3. **GET /v1/inbox** → *Execute* → your event, `unread_remaining: 0`.
4. *Execute* inbox again → empty (it was marked read on the first read).

## Option C — raw curl

```bash
BASE="https://<your-app>.up.railway.app"

# liveness (also confirms the DB connection when DATABASE_URL is set)
curl -s $BASE/healthz

# produce (201 new / 200 on a replayed event_id)
curl -s -X POST $BASE/v1/events \
  -H "Authorization: Bearer demo-key-a" -H "Content-Type: application/json" \
  -d '{"event_id":"evt-1","event_type":"order.created","payload":{"order_id":9931}}'

# consume (marks read, reports unread_remaining)
curl -s $BASE/v1/inbox -H "Authorization: Bearer demo-key-a"

# poll again -> empty
curl -s $BASE/v1/inbox -H "Authorization: Bearer demo-key-a"

# isolation: cust_b sees nothing of cust_a
curl -s $BASE/v1/inbox -H "Authorization: Bearer demo-key-b"
```

## Expected results at a glance

| Step | Expect |
|---|---|
| `GET /` | `404 {"detail":"Not Found"}` — there is no root route, this is normal |
| `GET /healthz` | `200 {"status":"ok"}` |
| `POST /v1/events` (new) | `201` · `{"...","deduped":false}` |
| `POST /v1/events` (same `event_id`) | `200` · `{"...","deduped":true}` |
| `GET /v1/inbox` (first) | your event(s), `unread_remaining:0`, marked read |
| `GET /v1/inbox` (second) | `{"events":[],"count":0,...}` |
| `GET /v1/last` | most-recent events, **read state untouched** |
| `GET /v1/inbox` with `demo-key-b` | empty — cross-tenant isolation |
| `GET /v1/inbox` with no key | `401` |

## Bulk load + verify by id

```bash
bash scripts/load.sh https://<your-app>.up.railway.app 20    # or: make load BASE=<url> N=20
```

Produces 20 events and looks each one up by id via `GET /v1/events/{id}`, printing
`stored: 20/20` and `verified: 20/20`. Set `KEY=demo-key-b` to run as the other tenant.

Single lookup by hand:

```bash
curl -s $BASE/v1/events/<event_id> -H "Authorization: Bearer demo-key-a"
# 200 with the event, or 404 if this customer has no such id
```

## Seeding extra customers

The two demo customers are always seeded. To add more, set `SEED_CUSTOMERS` (comma-separated
`id:api_key` pairs) and restart/redeploy:

```bash
SEED_CUSTOMERS="cust_c:key-c,cust_d:key-d"
# on Railway: API service -> Variables -> add it, which triggers a redeploy
```

Then those keys work exactly like the demo keys.

## Notes

- **In-memory vs Postgres:** `/healthz` returns `ok` either way. If you set
  `DATABASE_URL` (Railway Postgres), data survives redeploys; without it the app
  runs on the ephemeral in-memory backend.
- The demo keys are public on purpose — rotate them before real use.
