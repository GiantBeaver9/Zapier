"""The /inbox anti-join -- decisions D3, D12, D19.

Returns undelivered events, records the read on the 200, and a second poll does
not re-return them (single reader per event). unread_remaining reflects the
backlog past the 200 cap."""

from __future__ import annotations

from datetime import timedelta

from app.models import Customer
from tests.conftest import auth, utcnow


def _subscribe_old(store, customer_id="cust_a", api_key="demo-key-a"):
    """Re-subscribe a demo customer in the past so the retention floor is the
    31-day trail, not 'now' -- lets these tests ingest at the current instant
    without brushing the subscription floor."""
    store.upsert_customer(
        Customer(customer_id=customer_id, api_key=api_key, subscribed_at=utcnow() - timedelta(days=1))
    )


def test_inbox_returns_undelivered_then_marks_read(store):
    _subscribe_old(store)
    for i in range(3):
        store.ingest("cust_a", f"evt-{i}", "t", {"i": i})

    first = store.read_inbox("cust_a", subscribed_at=utcnow() - timedelta(days=1), limit=200)
    assert [e.event_id for e in first.events] == ["evt-0", "evt-1", "evt-2"]
    assert first.unread_remaining == 0

    second = store.read_inbox("cust_a", subscribed_at=utcnow() - timedelta(days=1), limit=200)
    assert second.events == []
    assert second.unread_remaining == 0


def test_inbox_http_roundtrip(client):
    client.post("/v1/events", headers=auth("demo-key-a"),
                json={"event_id": "e1", "payload": {"n": 1}})
    client.post("/v1/events", headers=auth("demo-key-a"),
                json={"event_id": "e2", "payload": {"n": 2}})

    body = client.get("/v1/inbox", headers=auth("demo-key-a")).json()
    assert body["count"] == 2
    assert body["unread_remaining"] == 0
    assert {e["event_id"] for e in body["events"]} == {"e1", "e2"}

    again = client.get("/v1/inbox", headers=auth("demo-key-a")).json()
    assert again["count"] == 0


def test_limit_caps_read_and_unread_remaining_reports_backlog(store):
    _subscribe_old(store)
    for i in range(3):
        store.ingest("cust_a", f"evt-{i}", "t", {"i": i})

    sub = utcnow() - timedelta(days=1)
    page1 = store.read_inbox("cust_a", subscribed_at=sub, limit=2)
    assert len(page1.events) == 2
    assert page1.unread_remaining == 1  # one still waiting

    page2 = store.read_inbox("cust_a", subscribed_at=sub, limit=2)
    assert len(page2.events) == 1
    assert page2.unread_remaining == 0


def test_inbox_limit_is_capped_at_200(client):
    r = client.get("/v1/inbox?limit=5000", headers=auth("demo-key-a"))
    assert r.status_code == 422  # ge=1, le=200 validation
