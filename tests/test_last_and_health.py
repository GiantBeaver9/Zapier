"""/last neutrality (D12), /healthz, and auth (D10)."""

from __future__ import annotations

from tests.conftest import auth


def test_last_returns_recent_regardless_of_delivered_and_records_nothing(client):
    for i in range(3):
        client.post("/v1/events", headers=auth("demo-key-a"),
                    json={"event_id": f"e{i}", "payload": {"i": i}})

    # Drain the inbox: all three are now delivered.
    client.get("/v1/inbox", headers=auth("demo-key-a"))

    # /last still shows them (delivered status is irrelevant to /last)...
    last = client.get("/v1/last?num=2", headers=auth("demo-key-a")).json()
    assert last["count"] == 2
    assert [e["event_id"] for e in last["events"]] == ["e2", "e1"]  # most-recent first

    # ...and reading /last did not un-deliver anything: inbox stays empty.
    inbox = client.get("/v1/inbox", headers=auth("demo-key-a")).json()
    assert inbox["count"] == 0
    assert inbox["unread_remaining"] == 0


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_missing_key_is_401(client):
    assert client.get("/v1/inbox").status_code == 401


def test_invalid_key_is_401(client):
    assert client.get("/v1/inbox", headers=auth("not-a-real-key")).status_code == 401
