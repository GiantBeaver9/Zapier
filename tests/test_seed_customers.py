"""SEED_CUSTOMERS parsing + startup seeding of extra tenants."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import parse_seed_customers
from app.main import app


def test_parse_pairs():
    assert parse_seed_customers("cust_c:key-c,cust_d:key-d") == [
        ("cust_c", "key-c"),
        ("cust_d", "key-d"),
    ]


def test_parse_skips_blank_and_malformed():
    assert parse_seed_customers(" cust_c : key-c , , bad-entry ,x:") == [("cust_c", "key-c")]


def test_parse_empty():
    assert parse_seed_customers(None) == []
    assert parse_seed_customers("") == []


def test_extra_customer_authenticates(monkeypatch):
    """A key set via SEED_CUSTOMERS works end-to-end after startup seeding."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("SEED_CUSTOMERS", "cust_c:key-c")
    with TestClient(app) as c:
        r = c.post("/v1/events", headers={"Authorization": "Bearer key-c"},
                   json={"event_id": "e1", "payload": {"hi": True}})
        assert r.status_code == 201
        got = c.get("/v1/events/e1", headers={"Authorization": "Bearer key-c"}).json()
        assert got["event_id"] == "e1"
        # isolation from the built-in demo customer still holds
        assert c.get("/v1/inbox", headers={"Authorization": "Bearer demo-key-a"}).json()["count"] == 0
