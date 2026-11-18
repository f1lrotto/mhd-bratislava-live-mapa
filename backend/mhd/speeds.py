"""Speed overlay: how long trips take between consecutive stops compared with the timetable.

A hop is a pair of consecutive stops of a trip pattern. Every trip whose stop events
(stopevents.py) record both stops of a hop is one run of it, with its scheduled and actual time
between them. A hop's ratio is its runs' actual time over their scheduled time (sums, so long and
short runs weigh by their length): above 1 the vehicles are slower than the timetable.

Two views:

* live: the runs that left the hop's first stop in the last LIVE_WINDOW_S, from the stop events
  of the latest polls (kept in memory; seeded from the raw logs at startup).
* typical: the runs on the same kind of day (workday, Saturday, Sunday) over the last
  TYPICAL_DAYS kept days (history/stop_events), in the half-hour slots around the time of day.
  Each kept day's runs are summed per hop, kind of day and half-hour slot once, into
  history/hop_times/<day>.parquet (a kept day never changes).

On the map the hops are merged into road segments (_geometry), so a street shows once per direction.
"""

from __future__ import annotations

import functools
import logging
import math
import threading
from bisect import bisect_left
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from .feed import REGIONAL
from .geo import Polyline, project_on_segment, to_lonlat, to_xy
from .logger import STOP_EVENT_SCHEMA, _atomic_write
from .planner import SHAPE_DETOUR, SHAPE_DETOUR_M, SHAPE_MAX_OFF_M, Planner
from .static import TZ

log = logging.getLogger(__name__)

LIVE_WINDOW_S = 30 * 60
LIVE_KEEP_S = LIVE_WINDOW_S + 15 * 60  # a run that left 30 min ago needs its first stop's event
LIVE_CACHE_S = 30
TYPICAL_DAYS = 28
SLOT_S = 30 * 60
TYPICAL_SLOTS = 1  # slots on each side of the current one: a 90-minute window
MIN_TYPICAL_RUNS = 3
# A hop's ratio counts PRIOR_S more seconds on schedule: a single run of a short hop, timed to
# within a poll (15 s), moves it only part of the way.
PRIOR_S = 60
# A run this much slower than scheduled is a vehicle that stopped (breakdown, detour, a GPS
# jump), not traffic.
MAX_FACTOR, MAX_EXTRA_S = 3, 15 * 60
KINDS = ("workday", "saturday", "sunday")
# A regional segment within OVERLAP_M of DPB's for OVERLAP_SHARE of its length runs on the same street.
OVERLAP_M, OVERLAP_SHARE, OVERLAP_CELL_M = 25.0, 0.8, 50.0
HOP_SCHEMA = pa.schema(
    [
        ("from", pa.string()),
        ("to", pa.string()),
        ("kind", pa.int8()),  # KINDS index of the local date the run left on
        ("slot", pa.int8()),  # half hour of local time the run left in, 0..47
        ("runs", pa.int32()),
        ("actual_s", pa.int64()),
        ("sched_s", pa.int64()),
    ]
)


def kind_of(d: date) -> int:
    return max(0, d.weekday() - 4)


def runs(events: pa.Table) -> pa.Table:
    """from, to, at (when it left `from`), sched_s, actual_s of every trip's run between two
    consecutive stops, from stop events with at most one row per trip and stop."""
    ev = events.select(["ts", "service_date", "trip", "seq", "stop", "scheduled", "actual"]).sort_by(
        [("service_date", "ascending"), ("trip", "ascending"), ("seq", "ascending")]
    )
    n = max(1, ev.num_rows)
    a, b = ev.slice(0, n - 1), ev.slice(1)
    seconds = lambda x, y: pc.cast(pc.cast(pc.subtract(y, x), pa.duration("s")), pa.int64())  # noqa: E731
    sched = seconds(a["scheduled"], b["scheduled"])
    actual = seconds(a["actual"], b["actual"])
    conds = [
        pc.equal(a["trip"], b["trip"]),
        pc.equal(a["service_date"], b["service_date"]),
        pc.equal(pc.add(pc.cast(a["seq"], pa.int32()), 1), pc.cast(b["seq"], pa.int32())),
        # Both stops recorded by one poll: the vehicle jumped past them (a late trip catching
        # up, a GPS jump) and their times are interpolated within the poll, not measured.
        pc.not_equal(a["ts"], b["ts"]),
        pc.greater_equal(actual, 0),
        pc.less_equal(actual, pc.add(pc.multiply(sched, MAX_FACTOR), MAX_EXTRA_S)),
    ]
    keep = functools.reduce(pc.and_, conds)
    t = pa.table({"from": a["stop"], "to": b["stop"], "at": a["actual"], "sched_s": sched, "actual_s": actual})
    return t.filter(keep)


def _sum(t: pa.Table, keys: list[str]) -> pa.Table:
    return t.group_by(keys, use_threads=False).aggregate(
        [("actual_s", "count"), ("actual_s", "sum"), ("sched_s", "sum")]
    )


def day_hop_times(events: pa.Table) -> pa.Table:
    """A day's runs summed per hop, kind of day and half-hour slot (HOP_SCHEMA)."""
    r = runs(events)
    local = r["at"].cast(pa.timestamp("s", tz=TZ.key))
    dow = pc.day_of_week(local)  # Monday = 0
    kind = pc.if_else(pc.less(dow, 5), 0, pc.subtract(dow, 4))
    slot = pc.add(pc.multiply(pc.hour(local), 2), pc.divide(pc.minute(local), 30))
    t = r.append_column("kind", pc.cast(kind, pa.int8())).append_column("slot", pc.cast(slot, pa.int8()))
    g = _sum(t, ["from", "to", "kind", "slot"])
    return pa.table(
        {
            "from": g["from"],
            "to": g["to"],
            "kind": g["kind"],
            "slot": g["slot"],
            "runs": pc.cast(g["actual_s_count"], pa.int32()),
            "actual_s": g["actual_s_sum"],
            "sched_s": g["sched_s_sum"],
        },
        schema=HOP_SCHEMA,
    )


def _hops_json(g: pa.Table, min_runs: int) -> list[dict]:
    """[{k: "from>to", n: runs, a: mean actual s, s: mean scheduled s, r: ratio}] from summed runs."""
    out = []
    for f, t, n, act, sch in zip(
        g["from"].to_pylist(), g["to"].to_pylist(), g["runs"].to_pylist(),
        g["actual_s"].to_pylist(), g["sched_s"].to_pylist(),
    ):
        if n >= min_runs and sch > 0:
            r = (act + PRIOR_S) / (sch + PRIOR_S)
            out.append({"k": f"{f}>{t}", "n": n, "a": round(act / n, 1), "s": round(sch / n, 1), "r": round(r, 2)})
    return out


class Speeds:
    def __init__(self, data_dir: Path):
        self.logs = data_dir / "logs"
        self.hist = data_dir / "history"
        self._events: dict[tuple, dict] = {}  # (service date, trip, seq) -> the first stop event
        self._lock = threading.Lock()  # typical and geometry: computed once by one request
        self._live_lock = threading.Lock()  # the poll adds events while a request reads them
        self._live: tuple[float, dict] | None = None
        self._typical: dict[tuple[date, int], dict] = {}  # (local date, slot) -> body, today only
        self._geometry: tuple[Planner, dict] | None = None

    # --- live ---------------------------------------------------------------------------------

    def add(self, events: list[dict]) -> None:
        """Stop events of the latest poll (StopEventTracker.update)."""
        with self._live_lock:
            for e in events:
                self._events.setdefault((e["service_date"], e["trip"], e["seq"]), e)

    def seed(self, now: datetime) -> None:
        """The last LIVE_KEEP_S of stop events from the raw logs, after a restart."""
        since = now - timedelta(seconds=LIVE_KEEP_S)
        h = since.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
        files: list[Path] = []
        while h <= now:
            d = self.logs / "stop_events" / f"date={h:%Y-%m-%d}"
            files += sorted(d.glob(f"hour={h:%H}.parquet")) + sorted(d.glob(f"hour={h:%H}.part-*.parquet"))
            h += timedelta(hours=1)
        tables = []
        for f in files:
            try:
                tables.append(pq.read_table(f, schema=STOP_EVENT_SCHEMA))
            except Exception:
                log.exception("unreadable log file %s", f)
        if tables:
            t = pa.concat_tables(tables).sort_by("ts")
            self.add(t.filter(pc.greater_equal(t["actual"], pa.scalar(since, t.schema.field("actual").type))).to_pylist())

    def live(self, now: datetime) -> dict:
        ts = now.timestamp()
        if self._live and ts - self._live[0] < LIVE_CACHE_S:
            return self._live[1]
        cutoff = now - timedelta(seconds=LIVE_KEEP_S)
        with self._live_lock:
            self._events = {k: e for k, e in self._events.items() if e["actual"] >= cutoff}
            rows = list(self._events.values())
        t = pa.Table.from_pylist(rows, schema=STOP_EVENT_SCHEMA)
        r = runs(t)
        r = r.filter(pc.greater_equal(r["at"], pa.scalar(now - timedelta(seconds=LIVE_WINDOW_S), r.schema.field("at").type)))
        g = _sum(r, ["from", "to"]).rename_columns(["from", "to", "runs", "actual_s", "sched_s"])
        body = {"view": "live", "windowS": LIVE_WINDOW_S, "hops": _hops_json(g, 1)}
        self._live = (ts, body)
        return body

    # --- typical ------------------------------------------------------------------------------

    def _day(self, day: date) -> pa.Table | None:
        """The day's summed runs, computed once from its kept stop events."""
        src = self.hist / "stop_events" / f"{day}.parquet"
        dst = self.hist / "hop_times" / f"{day}.parquet"
        if dst.exists():
            return pq.read_table(dst, schema=HOP_SCHEMA)
        if not src.exists():
            return None
        t = day_hop_times(pq.read_table(src, schema=STOP_EVENT_SCHEMA))
        dst.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(t, dst, compression="zstd")
        return t

    def typical(self, now: datetime, at: int | None = None) -> dict:
        """The typical runs around `at` (seconds after local midnight; default: now) on today's
        kind of day."""
        local = now.astimezone(TZ)
        today = local.date()
        if at is None:
            at = local.hour * 3600 + local.minute * 60
        slot = at % 86400 // SLOT_S
        key = (today, slot)
        with self._lock:
            if key in self._typical:
                return self._typical[key]
            self._typical = {k: v for k, v in self._typical.items() if k[0] == today}
            kind = kind_of(today)
            slots = [(slot + k) % 48 for k in range(-TYPICAL_SLOTS, TYPICAL_SLOTS + 1)]
            parts, days = [], 0
            for back in range(1, TYPICAL_DAYS + 1):
                d = today - timedelta(days=back)
                if kind_of(d) != kind:
                    continue
                try:
                    t = self._day(d)
                except Exception:
                    log.exception("failed to sum the hop times of %s", d)
                    continue
                if t is None:
                    continue
                days += 1
                parts.append(t.filter(pc.and_(pc.equal(t["kind"], kind), pc.is_in(t["slot"], pa.array(slots, pa.int8())))))
            hops: list[dict] = []
            if parts:
                g = pa.concat_tables(parts).group_by(["from", "to"], use_threads=False).aggregate(
                    [("runs", "sum"), ("actual_s", "sum"), ("sched_s", "sum")]
                ).rename_columns(["from", "to", "runs", "actual_s", "sched_s"])
                hops = _hops_json(g, MIN_TYPICAL_RUNS)
            first = slot - TYPICAL_SLOTS
            body = {
                "view": "typical",
                "kind": KINDS[kind],
                "days": days,
                "from": _hhmm(first * SLOT_S),
                "to": _hhmm((slot + TYPICAL_SLOTS + 1) * SLOT_S),
                "hops": hops,
            }
            self._typical[key] = body
            return body

    # --- geometry -----------------------------------------------------------------------------

    def geometry(self, planner: Planner) -> dict:
        """The overlay's map: {"hops": [{"k": "from>to", "m": metres, "lines": [...]}],
        "segments": [{"c": coordinates, "h": [indices of the hops that run it], "o": True where
        only regional hops run it, along a DPB street}]}."""
        with self._lock:
            if self._geometry is None or self._geometry[0] is not planner:
                self._geometry = (planner, _geometry(planner))
            return self._geometry[1]


def _geometry(planner: Planner) -> dict:
    """Each hop follows the street shape that fits it best (the planner's rule for drawing a ride),
    from the shape vertex nearest its first stop to the one nearest its second, so consecutive hops
    meet. Hops with no fitting shape aren't drawn. Shapes follow OSM ways, so hops on the same
    street share vertices: the road is split into its edges, each edge knows the hops that run it,
    and runs of edges with the same hops are joined into one segment. A street is then one line
    per direction however many lines and stop pairs use it."""
    best: dict[tuple[int, int], tuple[float, Polyline, float, float]] = {}
    lines: dict[tuple[int, int], set[str]] = defaultdict(set)
    for p, stops in enumerate(planner.pat_stops):
        projs = planner._projections(p)
        for i, (s0, s1) in enumerate(zip(stops, stops[1:])):
            if s0 == s1:
                continue
            lines[(s0, s1)].add(planner.pat_line[p])
            (ax, ay), (bx, by) = planner.stop_xy[s0], planner.stop_xy[s1]
            crow = math.hypot(bx - ax, by - ay)
            for pl, along, off in projs:
                worst, a0, a1 = max(off[i], off[i + 1]), along[i], along[i + 1]
                if (worst <= SHAPE_MAX_OFF_M and a0 < a1 <= a0 + SHAPE_DETOUR * crow + SHAPE_DETOUR_M
                        and ((s0, s1) not in best or worst < best[(s0, s1)][0])):
                    best[(s0, s1)] = (worst, pl, a0, a1)

    hops, edges = [], defaultdict(set)  # edge (vertex, vertex) -> indices of the hops on it
    for (s0, s1), (_, pl, a0, a1) in best.items():
        j0, j1 = _vertex(pl, a0), _vertex(pl, a1)
        if j1 <= j0:
            continue
        pts = [tuple(round(v, 5) for v in to_lonlat(*pl.xy[j])) for j in range(j0, j1 + 1)]
        k = len(hops)
        hops.append({"k": f"{planner.stop_ids[s0]}>{planner.stop_ids[s1]}", "m": round(pl.cum[j1] - pl.cum[j0]),
                     "lines": sorted(lines[(s0, s1)])})
        for e in zip(pts, pts[1:]):
            if e[0] != e[1]:
                edges[e].add(k)

    out_e, in_e = defaultdict(list), defaultdict(list)
    for u, v in edges:
        out_e[u].append(v)
        in_e[v].append(u)

    def only(cands: list) -> object | None:
        return cands[0] if len(cands) == 1 else None

    segments, seen = [], set()
    for e, hs in edges.items():
        if e in seen:
            continue
        # A segment continues through a vertex while one edge in and one out carry the same hops.
        same_in = lambda v: [u for u in in_e[v] if edges[(u, v)] == hs]  # noqa: E731
        same_out = lambda v: [w for w in out_e[v] if edges[(v, w)] == hs]  # noqa: E731
        u, v = e
        while len(same_out(u)) == 1 and (t := only(same_in(u))) is not None and (t, u) not in seen and (t, u) != e:
            u, v = t, u
        chain = [u, v]
        seen.add((u, v))
        while len(same_in(v)) == 1 and (w := only(same_out(v))) is not None and (v, w) not in seen:
            seen.add((v, w))
            chain.append(w)
            v = w
        segments.append({"c": [list(c) for c in chain], "h": sorted(hs)})
    _mark_regional_overlaps(segments, hops)
    return {"hops": hops, "segments": segments}


def _mark_regional_overlaps(segments: list[dict], hops: list[dict]) -> None:
    """Regional lines follow IDS BK's own shapes, which share no vertices with DPB's OSM routes, so
    in the city they would draw a second line beside DPB's on the same street. A segment of only
    regional hops that runs along DPB segments ("o": True) is left out of the network view."""
    regional = [h["k"].startswith(REGIONAL) for h in hops]
    grid: dict[tuple[int, int], list[tuple[float, float, float, float]]] = defaultdict(list)
    for seg in segments:
        if all(regional[i] for i in seg["h"]):
            continue
        xy = [to_xy(*c) for c in seg["c"]]
        for (ax, ay), (bx, by) in zip(xy, xy[1:]):
            for cell in _cells(ax, ay, bx, by):
                grid[cell].append((ax, ay, bx, by))

    def near(x: float, y: float) -> bool:
        cx, cy = int(x // OVERLAP_CELL_M), int(y // OVERLAP_CELL_M)
        return any(
            project_on_segment(x, y, *e)[1] <= OVERLAP_M
            for gx in (cx - 1, cx, cx + 1) for gy in (cy - 1, cy, cy + 1) for e in grid.get((gx, gy), ())
        )

    for seg in segments:
        if not all(regional[i] for i in seg["h"]):
            continue
        xy = [to_xy(*c) for c in seg["c"]]
        pts = [pt for (ax, ay), (bx, by) in zip(xy, xy[1:]) for pt in _along(ax, ay, bx, by)] + [xy[-1]]
        if sum(near(x, y) for x, y in pts) >= OVERLAP_SHARE * len(pts):
            seg["o"] = True


def _cells(ax: float, ay: float, bx: float, by: float) -> set[tuple[int, int]]:
    return {(int(x // OVERLAP_CELL_M), int(y // OVERLAP_CELL_M)) for x, y in _along(ax, ay, bx, by) + [(bx, by)]}


def _along(ax: float, ay: float, bx: float, by: float, step: float = 20.0) -> list[tuple[float, float]]:
    """Points every `step` metres from a towards b (a included, b not)."""
    n = max(1, math.ceil(math.hypot(bx - ax, by - ay) / step))
    return [(ax + (bx - ax) * i / n, ay + (by - ay) * i / n) for i in range(n)]


def _vertex(pl: Polyline, along: float) -> int:
    """The shape vertex nearest a distance along it."""
    j = bisect_left(pl.cum, along)
    if j >= len(pl.cum):
        return len(pl.cum) - 1
    return j - 1 if j > 0 and along - pl.cum[j - 1] < pl.cum[j] - along else j


def _hhmm(s: int) -> str:
    s %= 86400
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}"
