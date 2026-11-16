"""Fields derived from each poll: delay band, staleness, and (with static data) line matching."""

from __future__ import annotations

from datetime import datetime

from .feed import DELAY_CAP_S, Vehicle
from .poller import Snapshot

STALE_AFTER_S = 10 * 60
FEED_DOWN_AFTER_S = 3 * 60
LATE_S = 3 * 60

# Bands: 0 = on time (0–59 s), 1 = 1–3 min, 2 = 3–10 min, 3 = 10+ min, None = no data.
def delay_band(delay_s: int | None) -> int | None:
    if delay_s is None:
        return None
    if delay_s < 60:
        return 0
    if delay_s < 180:
        return 1
    if delay_s < 600:
        return 2
    return 3


def is_stale(v: Vehicle, snap: Snapshot, now: datetime) -> bool:
    """Position unchanged for 10 minutes while the record still has a line."""
    moved = snap.moved_at.get(v.key)
    return v.line is not None and moved is not None and (now - moved).total_seconds() >= STALE_AFTER_S


def vehicle_json(v: Vehicle, snap: Snapshot, now: datetime) -> dict:
    moved = snap.moved_at.get(v.key)
    return {
        "key": v.key,
        "line": v.line,
        "dest": v.dest,
        "type": v.type,
        "lat": v.lat,
        "lon": v.lon,
        "az": v.azimuth if v.azimuth is not None else snap.moved_bearing.get(v.key),
        "delay": v.delay_s,
        "delayCapped": v.delay_s is not None and v.delay_s >= DELAY_CAP_S,
        "band": delay_band(v.delay_s),
        "movedAgo": int((now - moved).total_seconds()) if moved else None,
        "stale": is_stale(v, snap, now),
    }


def feed_status(snap: Snapshot, now: datetime) -> dict:
    age = (now - snap.polled_at).total_seconds() if snap.polled_at else None
    return {
        "now": now.isoformat(),
        "polledAt": snap.polled_at.isoformat() if snap.polled_at else None,
        "attemptedAt": snap.attempted_at.isoformat() if snap.attempted_at else None,
        "error": snap.error,
        "down": age is None or age > FEED_DOWN_AFTER_S,
    }
