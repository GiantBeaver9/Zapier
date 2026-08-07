"""Shared fixtures. Everything runs against the in-memory backend -- no DB, no
network -- so the suite is the fast, self-contained correctness proof."""

from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, load_settings
from app.main import app, seed_demo_customers
from app.store import InMemoryEventStore


@pytest.fixture(autouse=True)
def _force_in_memory(monkeypatch):
    # Guarantee the app/store never reach for a real Postgres during tests.
    monkeypatch.delenv("DATABASE_URL", raising=False)


@pytest.fixture
def settings() -> Settings:
    return load_settings()


@pytest.fixture
def store(settings) -> InMemoryEventStore:
    """A bare store seeded with the demo customers (cust_a, cust_b)."""
    s = InMemoryEventStore(settings)
    seed_demo_customers(s, settings)
    return s


@pytest.fixture
def client() -> TestClient:
    """A TestClient whose lifespan builds the in-memory store and seeds demos."""
    with TestClient(app) as c:
        yield c


def auth(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
