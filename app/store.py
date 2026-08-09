"""Storage layer.

One interface, two backends:

* ``InMemoryEventStore``  -- the default; zero dependencies, used by the tests
  and by ``uvicorn`` when no ``DATABASE_URL`` is set.
* ``PostgresEventStore``  -- the durable backend used by ``docker compose up``.

The interface is deliberately thin (D20-ish: "storage sits behind a thin
interface so the in-memory dev backend and Postgres share one shape"). The
non-obvious part -- how /inbox reads undelivered events, records the read, and
reports the backlog -- lives in ONE place: ``EventStore.read_inbox`` composes
three primitives (``select_undelivered`` -> ``mark_delivered`` ->
``count_unread``) that each backend implements. That guarantees both backends
have byte-for-byte identical inbox semantics: an anti-join, served-then-marked,
lock-free, at-least-once.
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from . import retention
from .config import Settings
from .models import Customer, Event


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class IngestResult:
    event: Event
    deduped: bool


@dataclass(frozen=True)
class InboxResult:
    events: list[Event]
    unread_remaining: int


@dataclass(frozen=True)
class ArchiveResult:
    events_removed: int
    markers_removed: int


# --------------------------------------------------------------------------- #
# Interface
# --------------------------------------------------------------------------- #
class EventStore(ABC):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    # --- identity -------------------------------------------------------- #
    @abstractmethod
    def get_customer_by_api_key(self, api_key: str) -> Customer | None: ...

    @abstractmethod
    def upsert_customer(self, customer: Customer) -> None: ...

    # --- ingest (idempotent on (customer_id, event_id), D2) -------------- #
    @abstractmethod
    def ingest(
        self,
        customer_id: str,
        event_id: str,
        event_type: str | None,
        payload: dict[str, Any],
        created_at: datetime | None = None,
    ) -> IngestResult: ...

    # --- inbox primitives (composed by read_inbox below) ----------------- #
    @abstractmethod
    def select_undelivered(
        self, customer_id: str, subscribed_at: datetime, limit: int, now: datetime
    ) -> list[Event]: ...

    @abstractmethod
    def mark_delivered(self, customer_id: str, event_ids: list[str]) -> None: ...

    @abstractmethod
    def count_unread(self, customer_id: str, subscribed_at: datetime, now: datetime) -> int: ...

    # --- read-only peek -------------------------------------------------- #
    @abstractmethod
    def read_last(self, customer_id: str, num: int) -> list[Event]: ...

    @abstractmethod
    def get_event(self, customer_id: str, event_id: str) -> Event | None:
        """Fetch a single event by id for this customer. Read-only lookup --
        does not touch delivery state (like /last). Returns None if absent."""
        ...

    # --- retention ------------------------------------------------------- #
    @abstractmethod
    def archive_expired(self, now: datetime | None = None) -> ArchiveResult: ...

    # --- liveness / lifecycle ------------------------------------------- #
    @abstractmethod
    def ping(self) -> bool: ...

    def close(self) -> None:  # pragma: no cover - overridden where needed
        pass

    # --- the one composed operation, shared by every backend ------------- #
    def read_inbox(
        self, customer_id: str, subscribed_at: datetime, limit: int, now: datetime | None = None
    ) -> InboxResult:
        """Serve undelivered events, record the read, report the backlog.

        Served *then* marked (not marked-then-served) so concurrent polls are
        never serialized: two readers may briefly see the same event and both
        return it -- an accepted duplicate (at-least-once), consumers dedupe on
        ``event_id``. The read is the implicit ack (D13); ``unread_remaining``
        tells the caller whether more is waiting past the ``limit`` cap.
        """
        now = now or _utcnow()
        limit = max(0, min(limit, self.settings.response_item_cap))
        events = self.select_undelivered(customer_id, subscribed_at, limit, now)
        if events:
            self.mark_delivered(customer_id, [e.event_id for e in events])
        unread_remaining = self.count_unread(customer_id, subscribed_at, now)
        return InboxResult(events=events, unread_remaining=unread_remaining)


# --------------------------------------------------------------------------- #
# In-memory backend
# --------------------------------------------------------------------------- #
class InMemoryEventStore(EventStore):
    """Dict-backed store. Mutations are guarded by a lock only so the dev
    backend stays uncorrupted under uvicorn's threadpool -- the lock-free
    hot-path guarantee (D17) is a property of the Postgres backend, not this
    convenience one."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self._lock = threading.RLock()
        self._customers_by_key: dict[str, Customer] = {}
        self._events: dict[tuple[str, str], Event] = {}
        self._delivered: set[tuple[str, str]] = set()

    def get_customer_by_api_key(self, api_key: str) -> Customer | None:
        return self._customers_by_key.get(api_key)

    def upsert_customer(self, customer: Customer) -> None:
        with self._lock:
            self._customers_by_key[customer.api_key] = customer

    def ingest(
        self,
        customer_id: str,
        event_id: str,
        event_type: str | None,
        payload: dict[str, Any],
        created_at: datetime | None = None,
    ) -> IngestResult:
        key = (customer_id, event_id)
        with self._lock:
            existing = self._events.get(key)
            if existing is not None:
                # Replay of a known (customer_id, event_id): no-op, event untouched.
                return IngestResult(event=existing, deduped=True)
            event = Event(
                customer_id=customer_id,
                event_id=event_id,
                event_type=event_type,
                payload=payload,
                created_at=created_at or _utcnow(),
            )
            self._events[key] = event
            return IngestResult(event=event, deduped=False)

    def _undelivered(self, customer_id: str, floor: datetime) -> list[Event]:
        rows = [
            e
            for (cid, _eid), e in self._events.items()
            if cid == customer_id
            and (cid, e.event_id) not in self._delivered
            and e.created_at > floor
        ]
        rows.sort(key=lambda e: (e.created_at, e.event_id))
        return rows

    def select_undelivered(
        self, customer_id: str, subscribed_at: datetime, limit: int, now: datetime
    ) -> list[Event]:
        floor = retention.inbox_floor(subscribed_at, now, self.settings)
        with self._lock:
            return self._undelivered(customer_id, floor)[:limit]

    def mark_delivered(self, customer_id: str, event_ids: list[str]) -> None:
        with self._lock:
            for eid in event_ids:
                self._delivered.add((customer_id, eid))

    def count_unread(self, customer_id: str, subscribed_at: datetime, now: datetime) -> int:
        floor = retention.inbox_floor(subscribed_at, now, self.settings)
        with self._lock:
            return len(self._undelivered(customer_id, floor))

    def read_last(self, customer_id: str, num: int) -> list[Event]:
        num = max(0, min(num, self.settings.response_item_cap))
        with self._lock:
            rows = [e for (cid, _eid), e in self._events.items() if cid == customer_id]
        rows.sort(key=lambda e: (e.created_at, e.event_id), reverse=True)
        return rows[:num]

    def get_event(self, customer_id: str, event_id: str) -> Event | None:
        return self._events.get((customer_id, event_id))

    def archive_expired(self, now: datetime | None = None) -> ArchiveResult:
        now = now or _utcnow()
        cutoff = retention.archive_cutoff(now, self.settings)
        with self._lock:
            expired = [k for k, e in self._events.items() if e.created_at <= cutoff]
            for k in expired:
                del self._events[k]
            # Markers retire together with their event (same key shape).
            markers = {k for k in self._delivered if k in set(expired)}
            self._delivered -= markers
            return ArchiveResult(events_removed=len(expired), markers_removed=len(markers))

    def ping(self) -> bool:
        return True


# --------------------------------------------------------------------------- #
# Postgres backend
# --------------------------------------------------------------------------- #
class PostgresEventStore(EventStore):
    """Durable backend. Uses a psycopg3 connection pool. The inbox primitives
    are plain statements with no ``SELECT ... FOR UPDATE`` -- concurrent polls
    are never serialized (D17), duplicates are the accepted currency."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        # Imported lazily so the in-memory path (and the test suite) needs no
        # psycopg install.
        from psycopg_pool import ConnectionPool

        assert settings.database_url is not None
        self._pool = ConnectionPool(settings.database_url, min_size=1, max_size=10, open=True)

    # -- schema / seed ---------------------------------------------------- #
    def apply_migrations(self, sql: str) -> None:
        with self._pool.connection() as conn:
            conn.execute(sql)

    def get_customer_by_api_key(self, api_key: str) -> Customer | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT customer_id, api_key, subscribed_at FROM customers WHERE api_key = %s",
                (api_key,),
            ).fetchone()
        if row is None:
            return None
        return Customer(customer_id=row[0], api_key=row[1], subscribed_at=row[2])

    def upsert_customer(self, customer: Customer) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO customers (customer_id, api_key, subscribed_at)
                VALUES (%s, %s, %s)
                ON CONFLICT (customer_id) DO NOTHING
                """,
                (customer.customer_id, customer.api_key, customer.subscribed_at),
            )

    def ingest(
        self,
        customer_id: str,
        event_id: str,
        event_type: str | None,
        payload: dict[str, Any],
        created_at: datetime | None = None,
    ) -> IngestResult:
        from psycopg.types.json import Jsonb

        with self._pool.connection() as conn:
            # ON CONFLICT DO NOTHING makes a replay a no-op; RETURNING is null on
            # conflict, so a null return means "already stored" -> deduped.
            if created_at is None:
                row = conn.execute(
                    """
                    INSERT INTO events (customer_id, event_id, event_type, payload)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (customer_id, event_id) DO NOTHING
                    RETURNING created_at
                    """,
                    (customer_id, event_id, event_type, Jsonb(payload)),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    INSERT INTO events (customer_id, event_id, event_type, payload, created_at)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (customer_id, event_id) DO NOTHING
                    RETURNING created_at
                    """,
                    (customer_id, event_id, event_type, Jsonb(payload), created_at),
                ).fetchone()

            if row is not None:
                return IngestResult(
                    event=Event(customer_id, event_id, event_type, payload, row[0]),
                    deduped=False,
                )
            # Conflict: fetch and return the stored event untouched.
            existing = conn.execute(
                """
                SELECT event_id, event_type, payload, created_at
                FROM events WHERE customer_id = %s AND event_id = %s
                """,
                (customer_id, event_id),
            ).fetchone()
        return IngestResult(
            event=Event(customer_id, existing[0], existing[1], existing[2], existing[3]),
            deduped=True,
        )

    def select_undelivered(
        self, customer_id: str, subscribed_at: datetime, limit: int, now: datetime
    ) -> list[Event]:
        floor = retention.inbox_floor(subscribed_at, now, self.settings)
        with self._pool.connection() as conn:
            rows = conn.execute(
                """
                SELECT e.event_id, e.event_type, e.payload, e.created_at
                FROM events e
                LEFT JOIN delivered d USING (customer_id, event_id)
                WHERE e.customer_id = %s
                  AND d.event_id IS NULL
                  AND e.created_at > %s
                ORDER BY e.created_at, e.event_id
                LIMIT %s
                """,
                (customer_id, floor, limit),
            ).fetchall()
        return [Event(customer_id, r[0], r[1], r[2], r[3]) for r in rows]

    def mark_delivered(self, customer_id: str, event_ids: list[str]) -> None:
        if not event_ids:
            return
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO delivered (customer_id, event_id)
                    VALUES (%s, %s)
                    ON CONFLICT (customer_id, event_id) DO NOTHING
                    """,
                    [(customer_id, eid) for eid in event_ids],
                )

    def count_unread(self, customer_id: str, subscribed_at: datetime, now: datetime) -> int:
        floor = retention.inbox_floor(subscribed_at, now, self.settings)
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                SELECT count(*)
                FROM events e
                LEFT JOIN delivered d USING (customer_id, event_id)
                WHERE e.customer_id = %s
                  AND d.event_id IS NULL
                  AND e.created_at > %s
                """,
                (customer_id, floor),
            ).fetchone()
        return int(row[0])

    def read_last(self, customer_id: str, num: int) -> list[Event]:
        num = max(0, min(num, self.settings.response_item_cap))
        with self._pool.connection() as conn:
            rows = conn.execute(
                """
                SELECT event_id, event_type, payload, created_at
                FROM events
                WHERE customer_id = %s
                ORDER BY created_at DESC, event_id DESC
                LIMIT %s
                """,
                (customer_id, num),
            ).fetchall()
        return [Event(customer_id, r[0], r[1], r[2], r[3]) for r in rows]

    def get_event(self, customer_id: str, event_id: str) -> Event | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                SELECT event_id, event_type, payload, created_at
                FROM events WHERE customer_id = %s AND event_id = %s
                """,
                (customer_id, event_id),
            ).fetchone()
        if row is None:
            return None
        return Event(customer_id, row[0], row[1], row[2], row[3])

    def archive_expired(self, now: datetime | None = None) -> ArchiveResult:
        now = now or _utcnow()
        cutoff = retention.archive_cutoff(now, self.settings)
        with self._pool.connection() as conn:
            markers = conn.execute(
                """
                DELETE FROM delivered d
                USING events e
                WHERE d.customer_id = e.customer_id AND d.event_id = e.event_id
                  AND e.created_at <= %s
                """,
                (cutoff,),
            ).rowcount
            events = conn.execute(
                "DELETE FROM events WHERE created_at <= %s", (cutoff,)
            ).rowcount
        return ArchiveResult(events_removed=events, markers_removed=markers)

    def ping(self) -> bool:
        try:
            with self._pool.connection() as conn:
                conn.execute("SELECT 1")
            return True
        except Exception:  # pragma: no cover
            return False

    def close(self) -> None:
        self._pool.close()
