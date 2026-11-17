"""Runtime access to the static build: lines, shapes, stops, and the timetable for today."""

from __future__ import annotations

import json
import statistics
from array import array
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .geo import Polyline

TZ = ZoneInfo("Europe/Bratislava")


@dataclass
class Direction:
    line: str
    id: str
    headsign: str
    headsigns: list[str]
    stops: list[str]
    stop_dist: list[float]
    length: float
    duration: int | None  # median scheduled run time of the main pattern, seconds
    shape: Polyline
    coords: list[list[float]]
    # Shapes of branches that end at this direction's headsign but leave the main route
    branch_shapes: list[Polyline]
    branches: list[list[list[float]]]
    ref_stop: int  # index of the stop the timetable departures are timed at


class Static:
    def __init__(self, static_dir: Path):
        self.dir = static_dir
        self.lines: dict[str, dict] = json.loads((static_dir / "lines.json").read_text())
        self.stops: dict[str, dict] = json.loads((static_dir / "stops.json").read_text())
        self.meta: dict = json.loads((static_dir / "meta.json").read_text())
        service = json.loads((static_dir / "service.json").read_text())
        self.calendar: dict[str, dict] = service["calendar"]
        self.departures: dict[str, dict[str, dict[str, list[int]]]] = service["departures"]
        shapes = json.loads((static_dir / "shapes.json").read_text())
        branches_path = static_dir / "branches.json"
        branches = json.loads(branches_path.read_text()) if branches_path.exists() else {}

        self.directions: dict[str, dict[str, Direction]] = {}
        # (line, headsign) -> direction ids that list the headsign
        self.by_headsign: dict[tuple[str, str], list[str]] = {}
        for line, info in self.lines.items():
            for d, di in info["directions"].items():
                coords = shapes[line][d]
                bs = branches.get(line, {}).get(d, [])
                self.directions.setdefault(line, {})[d] = Direction(
                    line=line,
                    id=d,
                    headsign=di["headsign"],
                    headsigns=di["headsigns"],
                    stops=di["stops"],
                    stop_dist=di["stopDist"],
                    length=di["length"],
                    duration=di.get("duration"),
                    shape=Polyline([tuple(c) for c in coords]),
                    coords=coords,
                    branch_shapes=[Polyline([tuple(c) for c in b]) for b in bs],
                    branches=bs,
                    ref_stop=di.get("refStop", 0),
                )
                for h in di["headsigns"]:
                    self.by_headsign.setdefault((line, h), []).append(d)
        self._active_cache: dict[date, set[str]] = {}
        self._timetable: Timetable | None = None
        self.stations: dict[str, dict] = {}
        stations_path = static_dir / "stations.json"
        if stations_path.exists():
            self.stations = json.loads(stations_path.read_text())

    @property
    def timetable(self) -> Timetable | None:
        """Every trip of the build, loaded on first use. None when the build has no timetable."""
        if self._timetable is None:
            path = self.dir / "timetable.json"
            if not path.exists():
                return None
            self._timetable = Timetable(json.loads(path.read_text()), self)
        return self._timetable

    @classmethod
    def load(cls, data_dir: Path) -> Static | None:
        d = data_dir / "static"
        if not (d / "meta.json").exists():
            return None
        return cls(d)

    # --- timetable -----------------------------------------------------------------------------

    def active_services(self, day: date) -> set[str]:
        if day not in self._active_cache:
            ds = day.strftime("%Y%m%d")
            out = set()
            for sid, c in self.calendar.items():
                on = bool(c["days"][day.weekday()]) and c["start"] <= ds <= c["end"]
                if ds in c["added"]:
                    on = True
                if ds in c["removed"]:
                    on = False
                if on:
                    out.add(sid)
            self._active_cache[day] = out
        return self._active_cache[day]

    def departures_around(self, line: str, direction: str, now: datetime) -> list[int]:
        """Departures at the direction's reference stop as seconds after local midnight of `now`'s day, including trips
        of yesterday's service day that run past midnight (GTFS times above 24:00)."""
        local = now.astimezone(TZ)
        today = local.date()
        deps = self.departures.get(line, {}).get(direction, {})
        out: list[int] = []
        for day, offset in ((today, 0), (today - timedelta(days=1), -86400)):
            for sid in self.active_services(day):
                out.extend(t + offset for t in deps.get(sid, ()))
        return sorted(t for t in out if t >= -3600)

    def scheduled_interval(self, line: str, direction: str, now: datetime) -> int | None:
        """Median gap between departures at the reference stop in the current local hour, in seconds.

        The first departure of the next hour is included so an hour with one departure still has
        a gap. Returns None when the line doesn't run this hour."""
        local = now.astimezone(TZ)
        h0 = local.hour * 3600
        deps = self.departures_around(line, direction, now)
        in_hour = [t for t in deps if h0 <= t < h0 + 3600]
        if not in_hour:
            return None
        nxt = next((t for t in deps if t >= h0 + 3600), None)
        seq = in_hour + ([nxt] if nxt is not None and nxt - in_hour[-1] <= 3600 else [])
        gaps = [b - a for a, b in zip(seq, seq[1:]) if b > a]
        return int(statistics.median(gaps)) if gaps else None

    # --- matching ------------------------------------------------------------------------------

    def match_direction(
        self, line: str | None, dest: str | None, lon: float, lat: float, az: int | None
    ) -> tuple[Direction, float, float, float | None] | None:
        """The direction a vehicle runs in, with its distance along the main route, its distance
        from the main route and its distance from the nearest branch shape (None without
        branches), in metres. None for depot runs, unknown destinations and unknown lines."""
        if line is None or dest is None:
            return None
        cands = self.by_headsign.get((line, dest))
        if not cands:
            return None
        best = None
        for d in cands:
            dr = self.directions[line][d]
            along, off = dr.shape.project(lon, lat)
            # The nearest of the main shape and the branch shapes decides the score and heading.
            score, shape, at = off, dr.shape, along
            boff = None
            for bs in dr.branch_shapes:
                b_along, b_off = bs.project(lon, lat)
                boff = b_off if boff is None else min(boff, b_off)
                if b_off < score:
                    score, shape, at = b_off, bs, b_along
            if len(cands) > 1 and az is not None:
                b = shape.bearing_at(at)
                if b is not None and _angle_diff(b, az) > 90:
                    score += 500  # heading the wrong way along this direction
            if best is None or score < best[0]:
                best = (score, dr, along, off, boff)
        return best[1:]

    def stop_before(self, dr: Direction, along: float) -> int:
        """Index of the last stop at or before `along`."""
        i = 0
        for k, d in enumerate(dr.stop_dist):
            if d <= along + 1:
                i = k
            else:
                break
        return i


def _angle_diff(a: float, b: float) -> float:
    d = abs(a - b) % 360
    return 360 - d if d > 180 else d


def day_start(day: date) -> datetime:
    """Midnight of a service day as GTFS counts it, in UTC: noon minus 12 h, which differs from the
    wall clock's midnight on DST change days. (Subtracting in local time would keep wall-clock
    midnight, so the subtraction is done in UTC.)"""
    return datetime.combine(day, time(12), TZ).astimezone(timezone.utc) - timedelta(hours=12)


@dataclass
class Pattern:
    line: str
    dir: str | None
    stops: list[str]
    dist: list[float] | None  # each stop's distance along the direction's main shape (non-decreasing)


@dataclass(slots=True)
class Trip:
    id: str
    pattern: int
    svc: str
    head: str
    t: array  # seconds after service-day midnight at each stop of the pattern


class Timetable:
    """The trips of timetable.json, indexed by direction, pattern and stop."""

    def __init__(self, raw: dict, static: Static):
        self.patterns: list[Pattern] = []
        for p in raw["patterns"]:
            dr = static.directions.get(p["line"], {}).get(p["dir"]) if p["dir"] is not None else None
            self.patterns.append(Pattern(p["line"], p["dir"], p["stops"], _pattern_dist(p["stops"], dr, static)))
        self.trips: list[Trip] = [Trip(t["id"], t["p"], t["svc"], t["head"], array("i", t["t"])) for t in raw["trips"]]
        self.by_id: dict[str, int] = {t.id: i for i, t in enumerate(self.trips)}
        self.by_pattern: list[list[int]] = [[] for _ in self.patterns]
        self.by_direction: dict[tuple[str, str], list[int]] = {}
        for i, t in enumerate(self.trips):
            self.by_pattern[t.pattern].append(i)
            p = self.patterns[t.pattern]
            if p.dir is not None:
                self.by_direction.setdefault((p.line, p.dir), []).append(i)
        # stop id -> (pattern, index in the pattern), every index but the last (an arrival)
        self.by_stop: dict[str, list[tuple[int, int]]] = {}
        for pi, p in enumerate(self.patterns):
            for k, s in enumerate(p.stops[:-1]):
                self.by_stop.setdefault(s, []).append((pi, k))


def _pattern_dist(stops: list[str], dr: Direction | None, static: Static) -> list[float] | None:
    """Distance of each stop along the direction's main shape: the direction's own stop distances
    where the pattern shares its stops, otherwise the stop projected on the shape (branch stops
    land on the nearest point of the main route, which is only approximate)."""
    if dr is None:
        return None
    out: list[float] = []
    j = 0
    for s in stops:
        k = next((k for k in range(j, len(dr.stops)) if dr.stops[k] == s), None)
        if k is not None:
            out.append(dr.stop_dist[k])
            j = k + 1
            continue
        info = static.stops.get(s)
        prev = out[-1] if out else 0.0
        if info is None:
            out.append(prev)
            continue
        along, _ = dr.shape.project(info["lon"], info["lat"], lo=prev)
        out.append(max(prev, along))
    return out
