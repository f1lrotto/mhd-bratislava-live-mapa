"""Runtime access to the static build: lines, shapes, stops, and the timetable for today."""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from datetime import date, datetime, timedelta
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

        self.directions: dict[str, dict[str, Direction]] = {}
        # (line, headsign) -> direction ids that list the headsign
        self.by_headsign: dict[tuple[str, str], list[str]] = {}
        for line, info in self.lines.items():
            for d, di in info["directions"].items():
                coords = shapes[line][d]
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
                )
                for h in di["headsigns"]:
                    self.by_headsign.setdefault((line, h), []).append(d)
        self._active_cache: dict[date, set[str]] = {}

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
        """First-stop departures as seconds after local midnight of `now`'s day, including trips
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
        """Median gap between departures from the first stop in the current local hour, in seconds.

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
    ) -> tuple[Direction, float, float] | None:
        """The direction a vehicle runs in, with its distance along the route and its distance
        from the route (metres). None for depot runs, unknown destinations and unknown lines."""
        if line is None or dest is None:
            return None
        cands = self.by_headsign.get((line, dest))
        if not cands:
            return None
        best = None
        for d in cands:
            dr = self.directions[line][d]
            along, off = dr.shape.project(lon, lat)
            score = off
            if len(cands) > 1 and az is not None:
                b = dr.shape.bearing_at(along)
                if b is not None and _angle_diff(b, az) > 90:
                    score += 500  # heading the wrong way along this direction
            if best is None or score < best[0]:
                best = (score, dr, along, off)
        _, dr, along, off = best
        return dr, along, off

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
