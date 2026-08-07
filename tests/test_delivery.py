"""Delivery semantics -- decisions D13, D17.

Pull /inbox is at-least-once and lock-free: concurrent polls are not
serialized, so two readers may get the same event (an accepted duplicate), but
an event is never lost. Consumers dedupe on event_id."""

from __future__ import annotations

from datetime import timedelta

from app.models import Customer
from tests.conftest import utcnow


def _subscribe_old(store):
    store.upsert_customer(
        Customer(customer_id="cust_a", api_key="demo-key-a", subscribed_at=utcnow() - timedelta(days=1))
    )


def test_concurrent_polls_may_dupe_but_never_lose(store):
    """Simulate the race deterministically via the inbox primitives: two readers
    both SELECT before either MARKS -> both see the event (dupe), and after both
    mark, the backlog is zero (no loss)."""
    _subscribe_old(store)
    sub = utcnow() - timedelta(days=1)
    now = utcnow()
    store.ingest("cust_a", "evt", "t", {})

    # Both readers select before either records the read (lock-free hot path).
    r1 = store.select_undelivered("cust_a", sub, limit=200, now=now)
    r2 = store.select_undelivered("cust_a", sub, limit=200, now=now)
    assert [e.event_id for e in r1] == ["evt"]
    assert [e.event_id for e in r2] == ["evt"]  # at-least-once: duplicate delivery

    # Both record their read; the marker is idempotent.
    store.mark_delivered("cust_a", [e.event_id for e in r1])
    store.mark_delivered("cust_a", [e.event_id for e in r2])

    assert store.count_unread("cust_a", sub, now) == 0  # never lost, now delivered


def test_capped_reads_lose_nothing(store):
    """Draining in capped pages returns every event exactly once across pages --
    union == all, no loss."""
    _subscribe_old(store)
    sub = utcnow() - timedelta(days=1)
    for i in range(5):
        store.ingest("cust_a", f"evt-{i}", "t", {"i": i})

    seen: set[str] = set()
    while True:
        page = store.read_inbox("cust_a", subscribed_at=sub, limit=2)
        seen.update(e.event_id for e in page.events)
        if page.unread_remaining == 0:
            break
    assert seen == {f"evt-{i}" for i in range(5)}
