"""Polls the DPB feed every 15 s, whatever the number of users, and keeps the latest snapshot.

The snapshot also holds the regional buses of the latest IDS BK sweep (idsbk.Sweeper hands them
to apply_regional), so both sources share one vehicle list, one movement record and one
derivation; each keeps its own poll times and error."""

from __future__ import annotations

import asyncio
import logging
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable

import httpx

from . import feed
from .feed import Vehicle
from .logger import PollLogger

log = logging.getLogger(__name__)

# Vehicles report every 10–15 s (measured 16 Nov 2026), so 15 s catches nearly every update.
POLL_INTERVAL_S = 15
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
class SourceState:
    polled_at: datetime | None = None  # time of the last successful poll
    attempted_at: datetime | None = None
    error: str | None = None  # error of the last attempt, None if it succeeded


@dataclass
class Snapshot:
    vehicles: list[Vehicle] = field(default_factory=list)  # DPB's, then the regional buses
    # DPB's poll state (the same fields as SourceState, so derive.feed_status takes either)
    polled_at: datetime | None = None
    attempted_at: datetime | None = None
    error: str | None = None
    regional: SourceState = field(default_factory=SourceState)
    updated_at: datetime | None = None  # the newest data of either source: the snapshot's time
    moved_at: dict[str, datetime] = field(default_factory=dict)  # last time each vehicle moved
    # Bearing of each vehicle's last move, for vehicles whose feed azimuth is unknown.
    moved_bearing: dict[str, int] = field(default_factory=dict)
    # Trip each vehicle was assigned at the last derived poll (realtime.compute keeps it), so a
    # vehicle keeps its trip from poll to poll instead of a neighbour taking it on a near tie:
    # (trip id, its service day's midnight as a Unix time, time of that poll as a Unix time).
    trips: dict[str, tuple[str, int, float]] = field(default_factory=dict)

    def seen_at(self, key: str) -> datetime | None:
        """When the vehicle's source last reported it: the time its position is from."""
        return self.regional.polled_at if feed.is_regional(key) else self.polled_at


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
        self._dpb: list[Vehicle] = []  # the last successful poll's
        self._regional: list[Vehicle] = []  # the last successful sweep's

    def apply(self, vehicles: list[Vehicle], ts: datetime) -> None:
        """Update the snapshot with a successful DPB poll."""
        self._dpb = vehicles
        self._track(ts)
        self.snapshot = Snapshot(
            vehicles=self._dpb + self._regional,
            polled_at=ts,
            attempted_at=ts,
            error=None,
            regional=self.snapshot.regional,
            updated_at=ts,
            moved_at=self.snapshot.moved_at,
            moved_bearing=self.snapshot.moved_bearing,
            trips=self.snapshot.trips,
        )

    def apply_regional(self, ts: datetime, vehicles: list[Vehicle] | None, error: str | None = None) -> None:
        """Record an IDS BK sweep: its buses replace the last sweep's (None when it failed)."""
        s = self.snapshot
        s.regional = SourceState(polled_at=s.regional.polled_at if vehicles is None else ts, attempted_at=ts, error=error)
        if vehicles is None:
            return
        self._regional = vehicles
        self._track(ts)
        self.snapshot = Snapshot(
            vehicles=self._dpb + self._regional,
            polled_at=s.polled_at,
            attempted_at=s.attempted_at,
            error=s.error,
            regional=s.regional,
            updated_at=ts,
            moved_at=s.moved_at,
            moved_bearing=s.moved_bearing,
            trips=s.trips,
        )
        if self.on_update is not None:
            try:
                self.on_update(self.snapshot)
            except Exception:
                log.exception("on_update failed")

    def _track(self, ts: datetime) -> None:
        """Movement of every vehicle of both sources. A source's vehicles whose position didn't
        change (the other source just polled) don't count as moving."""
        vehicles = self._dpb + self._regional
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

    def restore(self, history: list[tuple[datetime, list[Vehicle]]]) -> None:
        """Replay logged DPB polls so a restart doesn't make every parked vehicle look as if it just
        moved. Only movement state is kept; the snapshot itself waits for the first live poll."""
        for ts, vehicles in history:
            self.apply(vehicles, ts)
        self._dpb = []
        s = self.snapshot
        self.snapshot = Snapshot(vehicles=self._regional, regional=s.regional, moved_at=s.moved_at, moved_bearing=s.moved_bearing)

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
        headers = {"User-Agent": "mhd-nazivo/0.1 (single server poller, every 15 s)"}
        if self.logger is not None:
            try:
                since = datetime.now(timezone.utc) - timedelta(minutes=15)
                self.restore(await asyncio.to_thread(self.logger.recent, since))
            except Exception:
                log.exception("could not restore movement state from the logs")
        async with httpx.AsyncClient(timeout=12, headers=headers) as client:
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
