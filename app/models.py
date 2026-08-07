"""Request/response shapes (Pydantic) and the internal record dataclasses.

The Pydantic models are the wire contract; the dataclasses (``Customer``,
``Event``) are what the store layer passes around.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Internal records (store layer)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Customer:
    customer_id: str
    api_key: str
    subscribed_at: datetime


@dataclass(frozen=True)
class Event:
    customer_id: str
    event_id: str
    event_type: str | None
    payload: dict[str, Any]
    created_at: datetime


# --------------------------------------------------------------------------- #
# Wire models
# --------------------------------------------------------------------------- #
class EventIn(BaseModel):
    """Ingest body. ``event_id`` is the producer-supplied idempotency key (D2)."""

    event_id: str = Field(..., min_length=1, description="Producer-supplied idempotency key.")
    event_type: str | None = Field(default=None)
    # JSONB is NOT NULL in the schema; default to {} so a payload-less event is
    # still valid rather than a 422.
    payload: dict[str, Any] = Field(default_factory=dict)


class IngestResponse(BaseModel):
    event_id: str
    status: str = "stored"
    deduped: bool


class EventOut(BaseModel):
    event_id: str
    event_type: str | None
    payload: dict[str, Any]
    created_at: datetime

    @classmethod
    def of(cls, e: Event) -> "EventOut":
        return cls(
            event_id=e.event_id,
            event_type=e.event_type,
            payload=e.payload,
            created_at=e.created_at,
        )


class InboxResponse(BaseModel):
    events: list[EventOut]
    count: int
    # How many still-undelivered events remain after this (capped) read -- the
    # "caught up?" signal (D6, D12).
    unread_remaining: int


class LastResponse(BaseModel):
    events: list[EventOut]
    count: int


class HealthResponse(BaseModel):
    status: str = "ok"
