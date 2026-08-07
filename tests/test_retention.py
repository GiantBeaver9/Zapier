"""Retention & the never-stale invariant -- decision D16.

Archival at 30d, inbox floor trailing at 31d. The floor sits a day behind
archival, so advancing it only ever retires already-archived events (no
resurrection) and never skips a live one (no premature loss)."""

from __future__ import annotations

from datetime import timedelta

from app.models import Customer
from tests.conftest import utcnow


def _long_lived_customer(store):
    """A customer old enough that the floor is the 31-day trail, not signup."""
    store.upsert_customer(
        Customer(customer_id="cust_a", api_key="demo-key-a", subscribed_at=utcnow() - timedelta(days=365))
    )


def test_inbox_floor_excludes_events_older_than_31_days(store):
    _long_lived_customer(store)
    now = utcnow()
    store.ingest("cust_a", "old", "t", {}, created_at=now - timedelta(days=40))
    store.ingest("cust_a", "mid", "t", {}, created_at=now - timedelta(days=20))
    store.ingest("cust_a", "new", "t", {}, created_at=now)

    result = store.read_inbox("cust_a", subscribed_at=now - timedelta(days=365), limit=200, now=now)
    ids = {e.event_id for e in result.events}
    assert ids == {"mid", "new"}  # 'old' is below the 31-day floor


def test_archive_removes_events_older_than_30_days(store):
    _long_lived_customer(store)
    now = utcnow()
    store.ingest("cust_a", "old", "t", {}, created_at=now - timedelta(days=40))
    store.ingest("cust_a", "mid", "t", {}, created_at=now - timedelta(days=20))

    res = store.archive_expired(now=now)
    assert res.events_removed == 1

    remaining = store.read_last("cust_a", num=200)
    assert {e.event_id for e in remaining} == {"mid"}


def test_floor_never_skips_a_live_event(store):
    """An event between the two horizons (age 30-31d) is the tight case: it must
    be archivable-soon but must NOT be skipped by the floor while still hot."""
    _long_lived_customer(store)
    now = utcnow()
    # age 25d: comfortably hot -- above the 31d floor AND under the 30d archive age.
    store.ingest("cust_a", "hot", "t", {}, created_at=now - timedelta(days=25))

    result = store.read_inbox("cust_a", subscribed_at=now - timedelta(days=365), limit=200, now=now)
    assert {e.event_id for e in result.events} == {"hot"}  # served, not skipped

    res = store.archive_expired(now=now)
    assert res.events_removed == 0  # still hot, not archived


def test_marker_retires_together_with_its_event(store):
    """No resurrection: when an event is archived its delivery marker goes too,
    so it can never reappear as 'undelivered'."""
    _long_lived_customer(store)
    now = utcnow()
    store.ingest("cust_a", "old", "t", {}, created_at=now - timedelta(days=40))
    store.mark_delivered("cust_a", ["old"])
    assert ("cust_a", "old") in store._delivered

    store.archive_expired(now=now)
    assert ("cust_a", "old") not in store._delivered  # marker retired with the event
