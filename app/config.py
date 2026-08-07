"""Runtime configuration.

All tunables live here so the values the PRD pins (retention window, response
cap) have exactly one home. Nothing in the app reads ``os.environ`` directly.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


# Demo customers. Seeded at startup with fixed, README-published keys so a
# reviewer can run the whole thing in one command -- no signup, no key minting.
# The api_key IS the credential; customer_id is derived from it (decision D10).
DEMO_CUSTOMERS: list[tuple[str, str]] = [
    ("cust_a", "demo-key-a"),
    ("cust_b", "demo-key-b"),
]


@dataclass(frozen=True)
class Settings:
    # When set, the app talks to Postgres; when None, it uses the in-memory
    # backend (the default for tests and `uvicorn` without a database).
    database_url: str | None = None

    # Retention (decision D16). Events + their delivery markers are archived out
    # of the hot store at ``archive_age_days``; the /inbox floor trails one day
    # behind at ``floor_trail_days`` so advancing it only ever retires
    # already-archived events -- never a live one, never a stale one.
    archive_age_days: int = 30
    floor_trail_days: int = 31

    # Response item cap for /inbox, /last (decision D19).
    response_item_cap: int = 200

    demo_customers: list[tuple[str, str]] = field(default_factory=lambda: list(DEMO_CUSTOMERS))


def load_settings() -> Settings:
    """Build Settings from the environment. Called once at startup."""
    return Settings(database_url=os.getenv("DATABASE_URL") or None)
