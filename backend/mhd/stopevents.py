"""Stop events: when each trip actually passed each stop, recorded live from consecutive polls.

A vehicle on the same trip in two polls close together has passed every stop its next stop index
advanced over. The time it passed stop k is interpolated between the two polls at the point where
the index advances (PASSED_M beyond the stop, so roughly its departure). A trip's last stop has no
departure, so it gets its arrival instead: the time the vehicle came within ARRIVE_M of it.
(About one trip in ten ends its run further from the stop and gets no arrival.)

These rows are kept forever; the raw poll logs they come from are not.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .realtime import PASSED_M, Realtime

MAX_GAP_S = 120  # polls further apart than this don't interpolate (the vehicle dropped out)
ARRIVE_M = 50  # this close to the last stop: arrived (realtime's 250 m layover zone is too early)


def _cross(t0: float, a0: float, t1: float, a1: float, at: float) -> float:
    """Time at which `along` reached `at`, moving from a0 at t0 to a1 at t1."""
    if a1 <= a0:
        return t1
    f = min(1.0, max(0.0, (at - a0) / (a1 - a0)))
    return t0 + f * (t1 - t0)


class StopEventTracker:
    def __init__(self) -> None:
        # vehicle key -> (trip id, trip start as a Unix time, poll time, along, next stop, arrived)
        self._last: dict[str, tuple[str, float, float, float, int, bool]] = {}
        # vehicle key -> (trip id, trip start, {stop index: Unix time it passed}) for its current trip
        self._passed: dict[str, tuple[str, float, dict[int, float]]] = {}

    def passed_at(self, rt: Realtime, key: str) -> dict[int, float]:
        """When the vehicle passed each stop of the trip `rt` assigns it, as far as recorded live."""
        a = rt.assigned.get(key)
        p = self._passed.get(key)
        if a is None or p is None or rt.base is None:
            return {}
        trip = rt.timetable.trips[a.trip]
        return p[2] if (p[0], p[1]) == (trip.id, rt.base.timestamp() + a.offset + trip.t[0]) else {}

    def update(self, rt: Realtime) -> list[dict]:
        tt = rt.timetable
        if tt is None or rt.now is None or rt.base is None:
            return []
        now = rt.now.timestamp()
        base = rt.base.timestamp()
        local_day = (rt.base + timedelta(hours=12)).date()  # rt.base is in UTC
        out: list[dict] = []
        last: dict[str, tuple[str, float, float, float, int, bool]] = {}
        passed: dict[str, tuple[str, float, dict[int, float]]] = {}
        for key, a in rt.assigned.items():
            trip = tt.trips[a.trip]
            pattern = tt.patterns[trip.pattern]
            dist = pattern.dist
            if any(d1 < d0 for d0, d1 in zip(dist, dist[1:])):
                continue  # a few branch patterns' stop distances run backwards (static._pattern_dist)
            start = base + a.offset + trip.t[0]
            end = len(dist) - 1
            next_stop = a.next_stop
            arrive_at = min(dist[-1], max(dist[-1] - ARRIVE_M, dist[-2] + PASSED_M)) if end else dist[-1]
            arrived = not a.waiting and a.along >= arrive_at
            p = self._passed.get(key)
            times = p[2] if p is not None and (p[0], p[1]) == (trip.id, start) else {}
            passed[key] = (trip.id, start, times)
            seen = a.seen if a.seen is not None else now  # when the vehicle was at a.along
            prev = self._last.get(key)
            if prev is not None and prev[2] == seen:  # its source hasn't polled since (or failed)
                last[key] = prev
                continue
            same_trip = prev is not None and prev[0] == trip.id and prev[1] == start
            if same_trip:
                # GPS jitter can move a vehicle back over a stop; never record a stop twice.
                next_stop, arrived = max(next_stop, prev[4]), arrived or prev[5]
            if same_trip and 0 < seen - prev[2] <= MAX_GAP_S:
                _, _, t0, a0, k0, was_arrived = prev
                events = [(k, dist[k] + PASSED_M) for k in range(k0, min(next_stop, end))]
                if arrived and not was_arrived:
                    events.append((end, arrive_at))
                if events:
                    day = local_day - timedelta(days=1) if a.offset else local_day
                    for k, at in events:
                        sched = base + a.offset + trip.t[k]
                        actual = _cross(t0, a0, seen, a.along, at)
                        times[k] = actual
                        out.append(
                            {
                                "ts": rt.now,
                                "service_date": day,
                                "trip": trip.id,
                                "line": pattern.line,
                                "dir": pattern.dir,
                                "seq": k,
                                "stop": pattern.stops[k],
                                "scheduled": datetime.fromtimestamp(sched, timezone.utc),
                                "actual": datetime.fromtimestamp(round(actual), timezone.utc),
                                "delay_s": round(actual - sched),
                                "vehicle": key,
                                "final": k == end,
                            }
                        )
            last[key] = (trip.id, start, seen, a.along, next_stop, arrived)
        # A vehicle can drop out of the assignment for a poll or two; keep its state meanwhile.
        for key, prev in self._last.items():
            if key not in last and now - prev[2] <= MAX_GAP_S:
                last[key] = prev
                if key in self._passed:
                    passed[key] = self._passed[key]
        self._last = last
        self._passed = passed
        return out
