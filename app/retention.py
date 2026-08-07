"""Retention math -- the "never stale" invariant (decision D16), in one place.

Two horizons, one day apart:

* **archive cutoff** = ``now - archive_age_days`` (30d). Events and their
  delivery markers are removed from the hot store at this age.
* **inbox floor**    = ``max(subscribed_at, now - floor_trail_days)`` (31d).
  The /inbox anti-join never looks below this line.

The floor trails the archive cutoff by a day. Because it sits *behind*
archival, advancing it can only ever retire events that are already archived
(no resurrection: event + marker retire together) and it never skips a
still-hot event (no premature loss). Net: we never scan or serve a stale event.

Both stores import these functions so the invariant is defined exactly once.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from .config import Settings


def archive_cutoff(now: datetime, settings: Settings) -> datetime:
    """Events strictly older than this are archived out of the hot store."""
    return now - timedelta(days=settings.archive_age_days)


def inbox_floor(subscribed_at: datetime, now: datetime, settings: Settings) -> datetime:
    """The oldest ``created_at`` the customer's /inbox will consider.

    A brand-new subscriber starts at their own subscription point; a long-lived
    one rides the trailing 31-day line -- whichever is later.
    """
    return max(subscribed_at, now - timedelta(days=settings.floor_trail_days))
