"""Line reliability: where along each direction delays build up, and when, from the kept history.

Reads the stop events (history/stop_events, retention.py) of the last WINDOW_DAYS days that are
kept, workdays (Mon–Fri) or weekends. A day counts once its history/delays file exists: retention
writes it last. The delays aggregates themselves can't serve here: their percentiles don't combine
across buckets and they don't know trips.

Per direction, each stop of the direction's main route × each hour of the service day (scheduled
time at that stop; 24+ is after midnight) gets the median and p90 delay, the share of passes
5+ min late and the number of passes. Per direction and for the whole line: p50 and p90 of all stop
passes, and the share of trips that were 5+ min late at some stop.
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as ds

from .derive import LATE_S
from .static import Static, day_start

WINDOW_DAYS = 28
MIN_CELL = 5  # fewer stop passes than this in a stop × hour cell give no value
KINDS = ("workdays", "weekends")
CACHE_SIZE = 64


def kept_days(hist: Path) -> list[date]:
    """The days whose history is complete, oldest first."""
    d = hist / "delays"
    return sorted(date.fromisoformat(p.stem) for p in d.glob("*.parquet")) if d.exists() else []


def window(days: list[date], kind: str) -> list[date]:
    """The days of the last WINDOW_DAYS before the newest kept day (inclusive) of that kind."""
    if not days:
        return []
    first = days[-1] - timedelta(days=WINDOW_DAYS - 1)
    weekend = kind == "weekends"
    return [d for d in days if d >= first and (d.weekday() >= 5) == weekend]


def _q(values: list[int], q: float) -> int:
    """Nearest-rank quantile of sorted values."""
    return values[max(0, math.ceil(q * len(values)) - 1)]


def _summary(delays: list[int], trip_max: list[int]) -> dict:
    delays = sorted(delays)
    return {
        "passes": len(delays),
        "trips": len(trip_max),
        "p50": _q(delays, 0.5) if delays else None,
        "p90": _q(delays, 0.9) if delays else None,
        "lateTrips": round(sum(d >= LATE_S for d in trip_max) / len(trip_max), 3) if trip_max else None,
    }


def line_reliability(hist: Path, static: Static, line: str, kind: str) -> dict | None:
    dirs = static.directions.get(line)
    if dirs is None:
        return None
    days = window(kept_days(hist), kind)
    files = [str(hist / "stop_events" / f"{d}.parquet") for d in days]
    files = [f for f in files if Path(f).exists()]
    rows: list[dict] = []
    if files:
        cols = ["service_date", "trip", "dir", "seq", "stop", "scheduled", "delay_s"]
        t = ds.dataset(files, format="parquet").to_table(columns=cols, filter=ds.field("line") == line)
        t = t.sort_by([("service_date", "ascending"), ("trip", "ascending"), ("seq", "ascending")])
        # Hour of the service day at each stop, computed in Arrow: Python datetimes are slow.
        starts = pa.array([int(day_start(d).timestamp()) for d in days], pa.int64())
        start = pc.take(starts, pc.index_in(t["service_date"], value_set=pa.array(days, pa.date32())))
        # (Parquet keeps second timestamps in milliseconds.)
        sched = pc.cast(pc.cast(t["scheduled"], pa.timestamp("s", tz="UTC")), pa.int64())
        secs = pc.subtract(sched, start)
        hour = pc.cast(pc.floor(pc.divide(pc.cast(secs, pa.float64()), 3600)), pa.int16())
        rows = t.drop_columns(["scheduled", "seq"]).append_column("hour", hour).to_pylist()

    stop_index = {d: dr.stops for d, dr in dirs.items()}
    # direction -> (stop index, hour) -> delays; direction -> delays at each stop (all hours)
    cells: dict[str, dict[tuple[int, int], list[int]]] = defaultdict(lambda: defaultdict(list))
    by_stop: dict[str, dict[int, list[int]]] = defaultdict(lambda: defaultdict(list))
    all_delays: dict[str, list[int]] = defaultdict(list)
    trip_max: dict[str, dict[tuple, int]] = defaultdict(dict)
    prev_trip, j = None, 0
    for r in rows:
        d = r["dir"]
        stops = stop_index.get(d)
        if stops is None:
            continue  # a direction of an older timetable
        key = (r["service_date"], r["trip"])
        if key != prev_trip:
            prev_trip, j = key, 0
        delay = r["delay_s"]
        all_delays[d].append(delay)
        tm = trip_max[d]
        tm[key] = max(tm.get(key, delay), delay)
        # The stop's place on the main route, walking forward along the trip (a loop passes a stop
        # twice). Stops of branches and detours aren't on it and get no row.
        k = next((k for k in range(j, len(stops)) if stops[k] == r["stop"]), None)
        if k is None:
            continue
        j = k + 1
        cells[d][(k, r["hour"])].append(delay)
        by_stop[d][k].append(delay)

    directions = []
    for d, dr in dirs.items():
        c = cells.get(d, {})
        hours = sorted({h for _, h in c})
        hours = list(range(hours[0], hours[-1] + 1)) if hours else []
        grid = {name: [[None] * len(hours) for _ in dr.stops] for name in ("median", "p90", "late", "n")}
        for (k, h), vals in c.items():
            i = h - hours[0]
            grid["n"][k][i] = len(vals)
            if len(vals) >= MIN_CELL:
                vals.sort()
                grid["median"][k][i] = round(statistics.median(vals))
                grid["p90"][k][i] = _q(vals, 0.9)
                grid["late"][k][i] = round(sum(v >= LATE_S for v in vals) / len(vals), 3)
        stop_median = [
            round(statistics.median(by_stop[d][k])) if len(by_stop[d].get(k, ())) >= MIN_CELL else None
            for k in range(len(dr.stops))
        ]
        directions.append(
            {
                "id": d,
                "headsign": dr.headsign,
                "from": static.stops[dr.stops[0]]["name"],
                "stops": [static.stops[s]["name"] for s in dr.stops],
                "hours": hours,
                **grid,
                "stopMedian": stop_median,
                "summary": _summary(all_delays.get(d, []), list(trip_max.get(d, {}).values())),
            }
        )
    return {
        "line": line,
        "kind": kind,
        "days": {"count": len(days), "from": str(days[0]) if days else None, "to": str(days[-1]) if days else None},
        "summary": _summary(
            [x for v in all_delays.values() for x in v], [x for v in trip_max.values() for x in v.values()]
        ),
        "directions": directions,
    }


class Reliability:
    """line_reliability, cached until a new day is kept or the static build changes."""

    def __init__(self, hist: Path):
        self.hist = hist
        self._cache: dict[tuple, dict | None] = {}

    def get(self, static: Static, line: str, kind: str) -> dict | None:
        days = kept_days(self.hist)
        key = (line, kind, days[-1] if days else None, len(days), id(static))
        if key not in self._cache:
            if len(self._cache) >= CACHE_SIZE:
                self._cache.pop(next(iter(self._cache)))
            self._cache[key] = line_reliability(self.hist, static, line, kind)
        return self._cache[key]
