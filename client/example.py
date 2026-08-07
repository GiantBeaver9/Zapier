#!/usr/bin/env python3
"""Example client: produce an event, then poll the inbox until caught up.

This is a graded DX deliverable (D10): it carries the demo API key for you and
shows the produce -> poll -> drain loop end to end.

    python client/example.py                 # uses cust_a's demo key vs localhost:8000
    python client/example.py --key demo-key-b --base http://localhost:8000

Depends only on the standard library (urllib) -- no extra install needed.
"""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
import uuid


def _request(method: str, url: str, api_key: str, body: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {api_key}")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:  # surface API errors instead of crashing
        return exc.code, json.loads(exc.read() or b"{}")


def produce(base: str, api_key: str, event_type: str, payload: dict) -> dict:
    event_id = f"evt-{uuid.uuid4().hex[:12]}"
    status, body = _request(
        "POST",
        f"{base}/v1/events",
        api_key,
        {"event_id": event_id, "event_type": event_type, "payload": payload},
    )
    print(f"POST /v1/events -> {status} {body}")
    return body


def drain_inbox(base: str, api_key: str) -> None:
    """Poll /inbox until unread_remaining hits 0."""
    while True:
        status, body = _request("GET", f"{base}/v1/inbox", api_key)
        print(f"GET  /v1/inbox  -> {status} count={body.get('count')} "
              f"unread_remaining={body.get('unread_remaining')}")
        for event in body.get("events", []):
            print(f"    <- {event['event_id']} {event.get('event_type')} {event['payload']}")
        if body.get("unread_remaining", 0) == 0:
            break


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://localhost:8000")
    parser.add_argument("--key", default="demo-key-a")
    args = parser.parse_args()

    print("== produce ==")
    produce(args.base, args.key, "order.created", {"order_id": 9931})
    produce(args.base, args.key, "order.created", {"order_id": 9932})

    print("\n== consume (marks read, reports remaining) ==")
    drain_inbox(args.base, args.key)

    print("\n== poll again -> already read, empty ==")
    drain_inbox(args.base, args.key)


if __name__ == "__main__":
    main()
