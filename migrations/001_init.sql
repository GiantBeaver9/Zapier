-- TriggersAPI schema (PRD §4). Idempotent: safe to apply on every startup.

-- Identity. The api_key IS the customer's credential; customer_id is derived
-- from it (D10). Demo: keys are seeded by the app and published in the README.
-- Prod: keys are hashed + rotated (documented, not built in v1).
CREATE TABLE IF NOT EXISTS customers (
  customer_id   TEXT PRIMARY KEY,
  api_key       TEXT UNIQUE NOT NULL,
  subscribed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- The event stream. The composite primary key IS the idempotency structure
-- (D2): a replayed (customer_id, event_id) hits ON CONFLICT and is deduped.
-- event_id is producer-supplied and required.
CREATE TABLE IF NOT EXISTS events (
  customer_id TEXT NOT NULL REFERENCES customers,
  event_id    TEXT NOT NULL,
  event_type  TEXT,
  payload     JSONB NOT NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (customer_id, event_id)
);

-- Drives both the /inbox anti-join and the retention floor scan.
CREATE INDEX IF NOT EXISTS events_customer_created_idx ON events (customer_id, created_at);

-- Delivery markers. Written lazily on read, one per (customer, event) actually
-- delivered (D3, D4). The /inbox anti-join is events LEFT JOIN delivered where
-- no marker exists.
CREATE TABLE IF NOT EXISTS delivered (
  customer_id  TEXT NOT NULL,
  event_id     TEXT NOT NULL,
  delivered_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (customer_id, event_id)
);
