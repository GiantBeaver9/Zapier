"""GET /v1/events/{event_id} -- read-only lookup by id.

Scoped to the authenticated customer, does not touch delivery state, 404 when
absent (so cross-tenant lookups are structurally impossible)."""

from __future__ import annotations

from tests.conftest import auth


def test_lookup_returns_the_event(client):
    client.post("/v1/events", headers=auth("demo-key-a"),
                json={"event_id": "evt-9931", "event_type": "order.created", "payload": {"o": 1}})

    r = client.get("/v1/events/evt-9931", headers=auth("demo-key-a"))
    assert r.status_code == 200
    body = r.json()
    assert body["event_id"] == "evt-9931"
    assert body["event_type"] == "order.created"
    assert body["payload"] == {"o": 1}


def test_missing_event_is_404(client):
    assert client.get("/v1/events/nope", headers=auth("demo-key-a")).status_code == 404


def test_lookup_is_cross_tenant_safe(client):
    client.post("/v1/events", headers=auth("demo-key-a"),
                json={"event_id": "secret", "payload": {}})
    # B looks up A's id -> 404 (it's scoped to B's derived customer_id)
    assert client.get("/v1/events/secret", headers=auth("demo-key-b")).status_code == 404


def test_lookup_does_not_mark_read(client):
    client.post("/v1/events", headers=auth("demo-key-a"),
                json={"event_id": "e1", "payload": {}})

    client.get("/v1/events/e1", headers=auth("demo-key-a"))  # lookup, not a consume

    inbox = client.get("/v1/inbox", headers=auth("demo-key-a")).json()
    assert {e["event_id"] for e in inbox["events"]} == {"e1"}  # still undelivered
