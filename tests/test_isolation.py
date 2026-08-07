"""Cross-tenant isolation -- decision D10.

customer_id is derived from the API key; there is no id to spoof. B's key can
never see A's events, on /inbox or /last."""

from __future__ import annotations

from tests.conftest import auth


def test_b_cannot_read_a_events(client):
    client.post("/v1/events", headers=auth("demo-key-a"),
                json={"event_id": "a-1", "payload": {"secret": "A"}})

    b_inbox = client.get("/v1/inbox", headers=auth("demo-key-b")).json()
    assert b_inbox["events"] == []
    assert b_inbox["unread_remaining"] == 0

    b_last = client.get("/v1/last", headers=auth("demo-key-b")).json()
    assert b_last["events"] == []

    a_inbox = client.get("/v1/inbox", headers=auth("demo-key-a")).json()
    assert {e["event_id"] for e in a_inbox["events"]} == {"a-1"}


def test_a_read_does_not_deliver_b_events(client):
    # A and B each post their own event_id; the delivered set is per-customer.
    client.post("/v1/events", headers=auth("demo-key-a"), json={"event_id": "x", "payload": {}})
    client.post("/v1/events", headers=auth("demo-key-b"), json={"event_id": "x", "payload": {}})

    client.get("/v1/inbox", headers=auth("demo-key-a"))  # A drains its own

    b_inbox = client.get("/v1/inbox", headers=auth("demo-key-b")).json()
    assert {e["event_id"] for e in b_inbox["events"]} == {"x"}  # B's copy still undelivered
