"""Polls the DPB feed every 30 s, whatever the number of users, and keeps the latest snapshot."""

from __future__ import annotations

import asyncio
import logging
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Awaitable, Callable

import httpx

from . import feed
from .feed import Vehicle
from .logger import PollLogger

log = logging.getLogger(__name__)

POLL_INTERVAL_S = 30
# A vehicle counts as having moved when its position changes by more than this. GPS jitter at a
# stop is a few metres; the feed rounds to ~0.1 m, so exact equality would be too strict.
MOVE_THRESHOLD_M = 10.0


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Equirectangular distance, accurate to well under 1% at city scale."""
    k = math.cos(math.radians((lat1 + lat2) / 2))
    dx = (lon2 - lon1) * k * 111_320.0
    dy = (lat2 - lat1) * 110_574.0
    return math.hypot(dx, dy)


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> int:
    k = math.cos(math.radians((lat1 + lat2) / 2))
    dx = (lon2 - lon1) * k
    dy = lat2 - lat1
    return int(round(math.degrees(math.atan2(dx, dy)))) % 360


@dataclass
class Snapshot:
    vehicles: list[Vehicle] = field(default_factory=list)
    polled_at: datetime | None = None  # time of the last successful poll
    attempted_at: datetime | None = None
    error: str | None = None  # error of the last attempt, None if it succeeded
    moved_at: dict[str, datetime] = field(default_factory=dict)  # last time each vehicle moved
    # Bearing of each vehicle's last move, for vehicles whose feed azimuth is unknown.
    moved_bearing: dict[str, int] = field(default_factory=dict)


class Poller:
    def __init__(
        self,
        logger: PollLogger | None,
        on_update: Callable[[Snapshot], None] | None = None,
        fetch: Callable[[httpx.AsyncClient], Awaitable[list[Vehicle]]] = feed.fetch,
    ):
        self.logger = logger
        self.on_update = on_update
        self._fetch = fetch
        self.snapshot = Snapshot()
        self._last_pos: dict[str, tuple[float, float]] = {}

    def apply(self, vehicles: list[Vehicle], ts: datetime) -> None:
        """Update the snapshot with a successful poll."""
        moved_at = self.snapshot.moved_at
        bearing = self.snapshot.moved_bearing
        for v in vehicles:
            prev = self._last_pos.get(v.key)
            if prev is None or distance_m(prev[0], prev[1], v.lat, v.lon) > MOVE_THRESHOLD_M:
                if prev is not None:
                    bearing[v.key] = bearing_deg(prev[0], prev[1], v.lat, v.lon)
                self._last_pos[v.key] = (v.lat, v.lon)
                moved_at[v.key] = ts
        present = {v.key for v in vehicles}
        for k in list(moved_at):
            if k not in present:
                del moved_at[k]
                bearing.pop(k, None)
                self._last_pos.pop(k, None)
        self.snapshot = Snapshot(
            vehicles=vehicles,
            polled_at=ts,
            attempted_at=ts,
            error=None,
            moved_at=moved_at,
            moved_bearing=bearing,
        )

    async def poll_once(self, client: httpx.AsyncClient) -> None:
        ts = datetime.now(timezone.utc)
        t0 = time.monotonic()
        vehicles: list[Vehicle] | None = None
        error: str | None = None
        try:
            vehicles = await self._fetch(client)
        except Exception as e:  # any failure, including a changed feed format, is a logged outage
            error = f"{type(e).__name__}: {e}"[:500]
        duration_ms = int((time.monotonic() - t0) * 1000)

        if vehicles is not None:
            self.apply(vehicles, ts)
        else:
            log.warning("poll failed: %s", error)
            self.snapshot.attempted_at = ts
            self.snapshot.error = error

        if self.logger is not None:
            await asyncio.to_thread(self.logger.log_poll, ts, vehicles, duration_ms, error)
        if self.on_update is not None:
            try:
                self.on_update(self.snapshot)
            except Exception:
                log.exception("on_update failed")

    async def run(self) -> None:
        headers = {"User-Agent": "mhd-nazivo/0.1 (single server poller, every 30 s)"}
        async with httpx.AsyncClient(timeout=20, headers=headers) as client:
            next_at = time.monotonic()
            while True:
                try:
                    await self.poll_once(client)
                except Exception:
                    log.exception("unexpected poll error")
                next_at += POLL_INTERVAL_S
                delay = next_at - time.monotonic()
                if delay < 0:  # fell behind (slow request); don't burst to catch up
                    next_at = time.monotonic()
                    delay = 0
                await asyncio.sleep(delay)
