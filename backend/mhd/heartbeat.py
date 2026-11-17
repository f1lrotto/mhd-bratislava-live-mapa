"""Feed heartbeat for monitoring: every 5 minutes the server tells PostHog whether each source's
positions are fresh. PostHog alerts on these events email when a feed goes stale, and also when
the events stop, which covers the server itself being down. Production only (app.py).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import httpx

from . import derive, feed
from .poller import Poller

POSTHOG_URL = "https://eu.i.posthog.com/batch/"
# The MHD project's token (FilipHupka organization): write-only and public, the frontend sends it too.
POSTHOG_KEY = "phc_woSi6RvGuWmZ6FByoucbcaY4v6R9GNYzMqhu8gbntojJ"
INTERVAL_S = 300

log = logging.getLogger(__name__)


def events(poller: Poller, now: datetime, regional: bool) -> list[dict]:
    """One `feed_heartbeat` per source: ok when the feed isn't down (derive.feed_status)."""
    snap = poller.snapshot
    sources = [("dpb", snap)] + ([("idsbk", snap.regional)] if regional else [])
    out = []
    for source, state in sources:
        status = derive.feed_status(state, now)
        polled = state.polled_at
        out.append({
            "event": "feed_heartbeat",
            "distinct_id": "mhd-server",
            "timestamp": now.isoformat(),
            "properties": {
                "source": source,
                "ok": not status["down"],
                "vehicles": sum(1 for v in snap.vehicles if feed.is_regional(v.key) == (source == "idsbk")),
                "age_s": round((now - polled).total_seconds()) if polled else None,
                "error": status["error"],
                "$process_person_profile": False,
            },
        })
    return out


async def run_forever(poller: Poller, regional: bool) -> None:
    async with httpx.AsyncClient(timeout=20) as client:
        while True:
            await asyncio.sleep(INTERVAL_S)
            try:
                batch = events(poller, datetime.now(timezone.utc), regional)
                r = await client.post(POSTHOG_URL, json={"api_key": POSTHOG_KEY, "batch": batch})
                r.raise_for_status()
            except Exception as e:  # a missed heartbeat is what the alert is for; keep going
                log.warning("feed heartbeat failed: %s", e)
