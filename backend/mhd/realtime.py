"""Per-poll trip matching, service state and predicted departures.

DPB's feed has no trip ids, so each vehicle with a matched direction is assigned the timetable trip
whose schedule at the vehicle's position best fits its reported delay. A regional bus names its
trip number, so it gets that trip (today's or yesterday's, whichever fits) and its reported delay.
That gives every vehicle a service state (running, laying over, going to the depot, parked,
unknown) and every assigned trip a prediction: scheduled times plus the vehicle's delay at the
stops it hasn't passed yet.
"""

from __future__ import annotations

import math
import time as _time
from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .derive import is_stale
from .feed import DELAY_CAP_S, Vehicle, capped
from .poller import Snapshot
from .static import TZ, Static, Timetable, day_start

OFF_ROUTE_M = 300  # further than this from its direction's route: not on its route
AT_END_M = 250  # this close to a terminus: laying over
PASSED_M = 30  # a stop this far behind the vehicle still counts as not passed (it's standing at it)
SPAN_BEFORE_S = 20 * 60  # candidate trips: from this long before the first departure…
SPAN_AFTER_S = 30 * 60  # …to this long after the last arrival
WAIT_S = 20 * 60  # a vehicle at the first stop takes a trip departing within this long
MAX_COST_S = 10 * 60
MAX_COST_NO_DELAY_S = 15 * 60  # without a reported delay the fit is looser
CAPPED_SLACK = 0.1  # cost per second of extra delay beyond the feed's 15-min cap…
CAPPED_MAX_S = 30 * 60  # …up to this delay
# Weaker evidence costs more, so a vehicle with a precise delay wins a trip both fit.
CAPPED_PENALTY_S = 180
NO_DELAY_PENALTY_S = 60
HEADSIGN_PENALTY_S = 300  # the trip's headsign isn't the vehicle's destination
# The feed never reports running early, and vehicles rarely run more than a minute or two ahead.
# A vehicle further ahead of a trip than this is on an earlier trip (or waiting), not this one.
EARLY_MAX_S = 180
# A vehicle standing at its trip's last stop has finished it; one still running wins the trip.
AT_END_PENALTY_S = 300
# A vehicle keeps the trip it ran at the last poll unless another vehicle fits it this much better…
STICKY_S = 120
# …and takes a trip it didn't run only within this much of its reported delay. The feed's delay
# lags, so a vehicle stuck on its trip may drift up to MAX_COST_S behind it; a vehicle that would
# start out that far behind a trip is running another one.
NEW_TRIP_LATE_S = 300
# A held trip only counts when it was held at a recent poll: after a feed outage the vehicle may
# have moved on to another trip, so it has to fit afresh.
HELD_MAX_AGE_S = 60
POSITION_LATE_S = 120  # predict from the position when it shows this much more delay than reported
DEPOT_NAMES = {"bojnická"}  # pull-in destinations that don't say "depo"

SERVICES = ("running", "layover", "depot", "parked", "unknown")


def is_depot(dest: str) -> bool:
    d = dest.strip().lower()
    return "depo" in d or d.startswith("dp.") or d in DEPOT_NAMES


@dataclass
class Assignment:
    trip: int  # index into Timetable.trips
    offset: int  # added to the trip's times: 0 for today's service day, about -86400 for yesterday's
    along: float
    next_stop: int  # index of the first stop of the trip not yet passed
    delay: int  # used for predictions, seconds
    uncertain: bool  # the feed's delay was capped at 15 min, so the real delay may be larger
    waiting: bool  # at the first stop before its departure
    seen: float | None = None  # Unix time the vehicle was at `along` (its source's poll)


@dataclass
class Realtime:
    """Everything computed once per poll about trips. Read-only after `compute`."""

    static: Static | None = None
    now: datetime | None = None
    base: datetime | None = None  # today's service-day midnight; times below are seconds after it
    yesterday_offset: int = -86400
    service: dict[str, str] = field(default_factory=dict)  # vehicle key -> service state
    assigned: dict[str, Assignment] = field(default_factory=dict)  # vehicle key -> trip
    by_trip: dict[str, str] = field(default_factory=dict)  # trip id -> vehicle key
    vehicles: dict[str, Vehicle] = field(default_factory=dict)
    elapsed_ms: float = 0.0

    @property
    def timetable(self) -> Timetable | None:
        return self.static.timetable if self.static else None

    def trip_id(self, key: str) -> str | None:
        a = self.assigned.get(key)
        return self.timetable.trips[a.trip].id if a is not None else None

    # --- for the planner ------------------------------------------------------------------------

    def trip_delays(self) -> dict[str, int]:
        """Delay of each trip run by a running vehicle with a known, uncapped delay: the delay the
        departure boards predict with (the reported one, or the position's when clearly later)."""
        out = {}
        for key, a in self.assigned.items():
            v = self.vehicles[key]
            if self.service.get(key) == "running" and v.delay_s is not None and not capped(v):
                out[self.timetable.trips[a.trip].id] = a.delay
        return out

    def trip_next_stop(self) -> dict[str, int]:
        """Index of the next stop of every assigned trip (0 while waiting at its first stop)."""
        return {self.timetable.trips[a.trip].id: a.next_stop for a in self.assigned.values()}

    def trip_vehicle(self) -> dict[str, str]:
        """Vehicle key of every assigned trip (running, or waiting at its first stop)."""
        return dict(self.by_trip)

    # --- times ----------------------------------------------------------------------------------

    def iso(self, s: float) -> str:
        return (self.base.astimezone(timezone.utc) + timedelta(seconds=round(s))).astimezone(TZ).isoformat()

    def now_s(self, now: datetime) -> float:
        return (now - self.base).total_seconds()

    def predicted_s(self, a: Assignment, k: int, now_s: float) -> float | None:
        """Predicted time at stop k of the vehicle's trip, None when it has passed the stop."""
        if k < a.next_stop:
            return None
        trip = self.timetable.trips[a.trip]
        return max(trip.t[k] + a.offset + a.delay, now_s)

    # --- views ----------------------------------------------------------------------------------

    def departures(self, stop_ids: list[str], now: datetime, horizon_s: int = 90 * 60) -> list[dict]:
        """Departures from the given stops in the next `horizon_s`, sorted by expected time.

        A trip's last stop is an arrival and is left out; so is a trip whose vehicle has already
        passed the stop."""
        tt = self.timetable
        if tt is None or self.base is None:
            return []
        static = self.static
        now_s = self.now_s(now)
        local = self.base + timedelta(hours=12)
        days = [
            (static.active_services(local.date()), 0),
            (static.active_services(local.date() - timedelta(days=1)), self.yesterday_offset),
        ]
        live = {(a.trip, a.offset): (key, a) for key, a in self.assigned.items()}
        out = []
        for sid in stop_ids:
            stop = static.stops.get(sid, {})
            for pi, k in tt.by_stop.get(sid, ()):
                pat = tt.patterns[pi]
                info = static.lines.get(pat.line, {})
                for ti in tt.by_pattern[pi]:
                    trip = tt.trips[ti]
                    for svcs, off in days:
                        if trip.svc not in svcs:
                            continue
                        sched = trip.t[k] + off
                        key, a = live.get((ti, off), (None, None))
                        if sched > now_s + horizon_s or (sched < now_s - 3600 and a is None):
                            continue
                        pred = None
                        if a is not None:
                            pred = self.predicted_s(a, k, now_s)
                            if pred is None:
                                continue  # already left this stop
                        expected = pred if pred is not None else sched
                        if expected < now_s - 60 or expected > now_s + horizon_s:
                            continue
                        out.append(
                            {
                                "line": pat.line,
                                "type": info.get("type"),
                                "color": info.get("color"),
                                "textColor": info.get("textColor"),
                                "headsign": trip.head,
                                "platform": stop.get("platform"),
                                "stopId": sid,
                                "scheduled": self.iso(sched),
                                "predicted": self.iso(pred) if pred is not None else None,
                                "minutes": max(0, int((expected - now_s) // 60)),
                                "live": a is not None,
                                "uncertain": a.uncertain if a is not None else False,
                                "vehicle": key,
                                "trip": trip.id,
                                "_t": expected,
                            }
                        )
        out.sort(key=lambda d: (d["_t"], d["line"]))
        for d in out:
            del d["_t"]
        return out

    def vehicle_trip(self, key: str, now: datetime, passed_at: dict[int, float] | None = None) -> dict | None:
        """The vehicle's assigned trip with its remaining stops, None without one. `passed` lists the
        stops behind it, each with when it passed it from `passed_at` (stop index -> Unix time)."""
        a = self.assigned.get(key)
        if a is None:
            return None
        tt = self.timetable
        trip = tt.trips[a.trip]
        pat = tt.patterns[trip.pattern]
        now_s = self.now_s(now)
        base_ts = self.base.timestamp()
        passed_at = passed_at or {}

        def stop(k: int) -> dict:
            sid = pat.stops[k]
            st = self.static.stops.get(sid, {})
            return {
                "stopId": sid,
                "index": k,
                "name": st.get("name"),
                "station": st.get("station"),
                "platform": st.get("platform"),
                "lat": st.get("lat"),
                "lon": st.get("lon"),
                "scheduled": self.iso(trip.t[k] + a.offset),
                "arrival": k == len(pat.stops) - 1,
            }

        stops = [
            {**stop(k), "predicted": self.iso(self.predicted_s(a, k, now_s))}
            for k in range(a.next_stop, len(pat.stops))
        ]
        passed = [
            {**stop(k), "actual": self.iso(passed_at[k] - base_ts) if k in passed_at else None}
            for k in range(a.next_stop)
        ]
        return {
            "id": trip.id,
            "line": pat.line,
            "dir": pat.dir,
            "headsign": trip.head,
            "start": self.iso(trip.t[0] + a.offset),
            "delay": a.delay,
            "uncertain": a.uncertain,
            "waiting": a.waiting,
            "stopCount": len(pat.stops),
            "stops": stops,
            "passed": passed,
        }


def _interp(dist: list[float], times, along: float) -> float:
    i = bisect_right(dist, along) - 1
    if i < 0:
        return times[0]
    if i >= len(dist) - 1:
        return times[-1]
    span = dist[i + 1] - dist[i]
    f = (along - dist[i]) / span if span > 0 else 0.0
    return times[i] + f * (times[i + 1] - times[i])


def compute(snap: Snapshot, static: Static | None, matches: dict, now: datetime | None = None) -> Realtime:
    """Assign vehicles to trips and give each its service state. `matches` is the per-poll
    direction match (vehicle key -> object with direction, along, off, on_branch)."""
    t0 = _time.perf_counter()
    now = now or snap.updated_at or snap.polled_at or datetime.now(timezone.utc)
    rt = Realtime(static=static, now=now, vehicles={v.key: v for v in snap.vehicles})
    local_day = now.astimezone(TZ).date()
    rt.base = day_start(local_day)
    rt.yesterday_offset = -round((rt.base - day_start(local_day - timedelta(days=1))).total_seconds())
    tt = static.timetable if static else None
    now_s = rt.now_s(now)

    candidates: list[tuple[Vehicle, object]] = []
    for v in snap.vehicles:
        if static is None or v.line is None or v.dest is None or v.line not in static.lines:
            s = "unknown"
        elif is_depot(v.dest):
            s = "depot"
        elif is_stale(v, snap, now):
            s = "parked"
        elif (m := matches.get(v.key)) is None:
            s = "unknown"
        elif m.off > OFF_ROUTE_M and not m.on_branch:
            s = "parked"
        else:
            candidates.append((v, m))
            continue
        rt.service[v.key] = s

    if tt is not None:
        days = [
            (static.active_services(local_day), 0),
            (static.active_services(local_day - timedelta(days=1)), rt.yesterday_offset),
        ]
        active: dict[tuple[str, str], list[tuple[int, int]]] = {}

        def trips_of(line: str, d: str) -> list[tuple[int, int]]:
            if (line, d) not in active:
                out = []
                for ti in tt.by_direction.get((line, d), ()):
                    trip = tt.trips[ti]
                    for svcs, off in days:
                        if trip.svc in svcs and trip.t[0] + off - SPAN_BEFORE_S <= now_s <= trip.t[-1] + off + SPAN_AFTER_S:
                            out.append((ti, off))
                active[(line, d)] = out
            return active[(line, d)]

        # Held trips are keyed by their start as a Unix time, so they survive the change of service
        # day at local midnight (offset 0 becomes -86400) and DST days.
        base_ts = round(rt.base.timestamp())
        now_ts = now.timestamp()
        prev = {k: (tid, t0) for k, (tid, t0, at) in snap.trips.items() if now_ts - at <= HELD_MAX_AGE_S}
        pairs = []
        # Each vehicle is judged at the time its position is from: the other source may have
        # polled since.
        seen = {v.key: rt.now_s(snap.seen_at(v.key) or now) for v, _ in candidates}
        for v, m in candidates:
            named = str(v.trip_no) if v.trip_no is not None else None
            vnow = seen[v.key]
            for ti, off in trips_of(v.line, m.direction):
                trip = tt.trips[ti]
                if named is not None and trip.no != named:
                    continue
                dist = tt.patterns[trip.pattern].dist
                if named is None and (m.along < dist[0] - AT_END_M or m.along > dist[-1] + AT_END_M):
                    continue  # this trip starts later or ends earlier along the route
                start = trip.t[0] + off
                held = prev.get(v.key) == (trip.id, base_ts + off)
                waiting = m.along <= dist[0] + AT_END_M and vnow < start
                if waiting:
                    cost, limit = start - vnow, WAIT_S
                elif named is not None:
                    # The feed says which trip it is; the fit only picks today's or yesterday's.
                    sched = _interp(dist, trip.t, m.along) + off
                    cost, limit = abs(sched - (vnow - (v.delay_s or 0))), math.inf
                else:
                    sched = _interp(dist, trip.t, m.along) + off
                    d = v.delay_s
                    if not capped(v) and vnow - sched < -EARLY_MAX_S:
                        continue  # the vehicle would be running this trip far ahead of time
                    if d is None:
                        cost, limit = abs(sched - vnow), MAX_COST_NO_DELAY_S
                        cost += NO_DELAY_PENALTY_S
                    elif capped(v):
                        target = vnow - DELAY_CAP_S
                        cost = sched - target if sched > target else (target - sched) * CAPPED_SLACK
                        limit = MAX_COST_S if vnow - sched <= CAPPED_MAX_S else -1
                        cost += CAPPED_PENALTY_S
                    else:
                        cost = abs(sched - (vnow - d))
                        limit = MAX_COST_S if held else NEW_TRIP_LATE_S
                if cost <= limit:
                    if trip.head != v.dest:
                        cost += HEADSIGN_PENALTY_S
                    if not waiting and m.along >= dist[-1] - AT_END_M:
                        cost += AT_END_PENALTY_S
                    if held:
                        cost -= STICKY_S
                    pairs.append((cost, v.key, ti, off, waiting))
        pairs.sort(key=lambda p: p[0])
        by_key = {v.key: (v, m) for v, m in candidates}
        taken: set[tuple[int, int]] = set()
        for cost, key, ti, off, waiting in pairs:
            if key in rt.assigned or (ti, off) in taken:
                continue
            taken.add((ti, off))
            v, m = by_key[key]
            vnow = seen[key]
            trip = tt.trips[ti]
            dist = tt.patterns[trip.pattern].dist
            sched = _interp(dist, trip.t, m.along) + off
            d = v.delay_s
            if waiting:
                delay, uncertain = 0, False
            elif d is None:
                delay, uncertain = max(0, round(vnow - sched)), False
            elif v.trip_no is not None:
                # Regional: whole minutes and uncapped. Positions on a variant route are only
                # projected onto the direction's main route, too rough to correct the delay with.
                delay, uncertain = d, False
            elif capped(v):
                delay, uncertain = max(DELAY_CAP_S, round(vnow - sched)), True
            else:
                # The feed's delay lags (and is never negative); when the position shows the
                # vehicle clearly later than reported, predict from the position.
                pos = round(vnow - sched)
                delay, uncertain = (pos if pos > d + POSITION_LATE_S else d), False
            rt.assigned[key] = Assignment(
                trip=ti,
                offset=off,
                along=m.along,
                next_stop=bisect_right(dist, m.along - PASSED_M) if not waiting else 0,
                delay=delay,
                uncertain=uncertain,
                waiting=waiting,
                seen=rt.base.timestamp() + vnow,
            )
            rt.by_trip[trip.id] = key

    for v, m in candidates:
        dr = static.directions[v.line][m.direction]
        a = rt.assigned.get(v.key)
        at_end = m.along >= dr.length - AT_END_M
        if a is not None:
            dist = tt.patterns[tt.trips[a.trip].pattern].dist
            at_end = at_end or m.along >= dist[-1] - AT_END_M
            rt.service[v.key] = "layover" if a.waiting or at_end else "running"
        elif at_end or m.along <= dr.stop_dist[0] + AT_END_M:
            rt.service[v.key] = "layover"
        elif v.delay_s is not None and not capped(v) and (tt is None or trips_of(v.line, m.direction)):
            # Moving along its route but fitting no free trip, while its direction runs: mostly
            # the second of two bunched vehicles that fit the same trip. It runs, so it still
            # counts for gaps and bunching, just without a trip (or predictions). Without a
            # timetable there is nothing to check against.
            rt.service[v.key] = "running"
        else:
            # A capped or missing delay with no trip to fit (a depot yard beside the route), or
            # nothing scheduled around now (after the line's last trip): not known to run.
            rt.service[v.key] = "unknown"
    if tt is not None:
        snap.trips.clear()
        snap.trips.update({k: (tt.trips[a.trip].id, base_ts + a.offset, now_ts) for k, a in rt.assigned.items()})
    rt.elapsed_ms = (_time.perf_counter() - t0) * 1000
    return rt
