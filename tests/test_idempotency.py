"""Ingest is idempotent on (customer_id, event_id) -- decision D2.

A replayed event_id is a no-op: 200 deduped, and the *stored* event is left
untouched (a second POST with a different payload does not overwrite)."""

from __future__ import annotations

from tests.conftest import auth


def test_new_event_is_201_not_deduped(client):
    r = client.post(
        "/v1/events",
        headers=auth("demo-key-a"),
        json={"event_id": "evt-1", "event_type": "order.created", "payload": {"order_id": 1}},
    )
    assert r.status_code == 201
    assert r.json() == {"event_id": "evt-1", "status": "stored", "deduped": False}


def test_replay_is_200_deduped_and_leaves_event_untouched(client):
    first = {"event_id": "evt-1", "event_type": "order.created", "payload": {"order_id": 1}}
    client.post("/v1/events", headers=auth("demo-key-a"), json=first)

    # Same event_id, different payload -> deduped, original wins.
    replay = {"event_id": "evt-1", "event_type": "order.changed", "payload": {"order_id": 999}}
    r = client.post("/v1/events", headers=auth("demo-key-a"), json=replay)
    assert r.status_code == 200
    assert r.json()["deduped"] is True

    peek = client.get("/v1/last", headers=auth("demo-key-a")).json()
    assert peek["count"] == 1
    stored = peek["events"][0]
    assert stored["event_type"] == "order.created"
    assert stored["payload"] == {"order_id": 1}


def test_event_id_is_required(client):
    r = client.post("/v1/events", headers=auth("demo-key-a"), json={"payload": {}})
    assert r.status_code == 422  # missing required idempotency key
