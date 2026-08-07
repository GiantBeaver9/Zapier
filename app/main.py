"""FastAPI application: routes, dependency wiring, startup/seed.

Routes (base path ``/v1``; ``/healthz`` at root):

    POST /v1/events        ingest an event (idempotent)      201 new / 200 dupe
    GET  /v1/inbox?limit=  undelivered events, marks read     200
    GET  /v1/last?num=     most-recent N, read-only peek       200
    GET  /healthz          liveness                            200
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, Query, Response, status

from .auth import require_customer
from .config import Settings, load_settings
from .models import (
    Customer,
    EventIn,
    EventOut,
    HealthResponse,
    InboxResponse,
    IngestResponse,
    LastResponse,
)
from .store import EventStore, InMemoryEventStore, PostgresEventStore

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def build_store(settings: Settings) -> EventStore:
    """Pick the backend: Postgres when DATABASE_URL is set, else in-memory."""
    if settings.database_url:
        store = PostgresEventStore(settings)
        _apply_migrations(store)
        return store
    return InMemoryEventStore(settings)


def _apply_migrations(store: PostgresEventStore) -> None:
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        store.apply_migrations(path.read_text())


def seed_demo_customers(store: EventStore, settings: Settings) -> None:
    """Upsert the README-published demo customers so the demo runs signup-free.

    ``subscribed_at`` is set to now: a demo customer sees every event posted
    after startup (the /inbox floor is anchored at their subscription point).
    """
    now = datetime.now(timezone.utc)
    for customer_id, api_key in settings.demo_customers:
        store.upsert_customer(Customer(customer_id=customer_id, api_key=api_key, subscribed_at=now))


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = load_settings()
    store = build_store(settings)
    seed_demo_customers(store, settings)
    app.state.settings = settings
    app.state.store = store
    try:
        yield
    finally:
        store.close()


app = FastAPI(
    title="TriggersAPI",
    version="1.0.0",
    summary="Public event ingress + per-customer pull inbox (the reacting half of an automation platform).",
    lifespan=lifespan,
)


def _store(app_: FastAPI) -> EventStore:
    return app_.state.store


@app.post("/v1/events", response_model=IngestResponse, status_code=status.HTTP_201_CREATED)
def ingest_event(
    body: EventIn,
    response: Response,
    customer: Customer = Depends(require_customer),
) -> IngestResponse:
    """Ingest an event. Idempotent on ``(customer_id, event_id)`` -- a replay of
    a known ``event_id`` is a no-op that returns ``200`` with ``deduped: true``
    and leaves the stored event untouched."""
    result = _store(app).ingest(
        customer_id=customer.customer_id,
        event_id=body.event_id,
        event_type=body.event_type,
        payload=body.payload,
    )
    response.status_code = status.HTTP_200_OK if result.deduped else status.HTTP_201_CREATED
    return IngestResponse(event_id=result.event.event_id, status="stored", deduped=result.deduped)


@app.get("/v1/inbox", response_model=InboxResponse)
def read_inbox(
    customer: Customer = Depends(require_customer),
    limit: int = Query(default=200, ge=1, le=200),
) -> InboxResponse:
    """Return this customer's undelivered events (anti-join), record the read on
    the way out (implicit ack), and report ``unread_remaining`` -- the backlog
    still waiting past the ``limit`` cap. At-least-once, lock-free."""
    result = _store(app).read_inbox(
        customer_id=customer.customer_id, subscribed_at=customer.subscribed_at, limit=limit
    )
    return InboxResponse(
        events=[EventOut.of(e) for e in result.events],
        count=len(result.events),
        unread_remaining=result.unread_remaining,
    )


@app.get("/v1/last", response_model=LastResponse)
def read_last(
    customer: Customer = Depends(require_customer),
    num: int = Query(default=50, ge=1, le=200),
) -> LastResponse:
    """Most-recent ``num`` events regardless of delivered status -- a read-only
    debug peek. Does NOT record a read or touch delivery state (D12)."""
    events = _store(app).read_last(customer_id=customer.customer_id, num=num)
    return LastResponse(events=[EventOut.of(e) for e in events], count=len(events))


@app.get("/healthz", response_model=HealthResponse)
def healthz() -> HealthResponse:
    ok = _store(app).ping()
    if not ok:  # pragma: no cover
        raise_unavailable()
    return HealthResponse(status="ok")


def raise_unavailable() -> None:  # pragma: no cover
    from fastapi import HTTPException

    raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="store unavailable")
