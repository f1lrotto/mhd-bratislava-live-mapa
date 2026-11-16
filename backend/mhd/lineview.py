"""Per-poll matching of vehicles to timetable directions, the line view, and the city status."""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from .derive import LATE_S, is_stale
from .feed import Vehicle
from .poller import Snapshot
from .static import Static

GAP_FACTOR = 1.5
BUNCH_FACTOR = 0.3
OFF_ROUTE_M = 300  # further than this from its direction's route: shown on the map, not the ribbon
AT_START_M = 250  # vehicles this close to the first stop are laying over, not yet running
WORST_MIN_VEHICLES = 3


@dataclass
class Match:
    direction: str
    along: float
    off: float  # from the main route
    branch_off: float | None = None  # from the nearest branch shape, None without branches

    @property
    def on_branch(self) -> bool:
        """Off the main route but on one of the direction's branches (line 4 to Stn. Nové Mesto)."""
        return self.off > OFF_ROUTE_M and self.branch_off is not None and self.branch_off <= OFF_ROUTE_M


@dataclass
class Derived:
    """Everything computed once per poll from the snapshot and the static build."""

    polled_at: datetime | None = None
    matches: dict[str, Match] = field(default_factory=dict)  # vehicle key -> match


def derive_poll(snap: Snapshot, static: Static | None) -> Derived:
    out = Derived(polled_at=snap.polled_at)
    if static is None:
        return out
    for v in snap.vehicles:
        az = v.azimuth if v.azimuth is not None else snap.moved_bearing.get(v.key)
        m = static.match_direction(v.line, v.dest, v.lon, v.lat, az)
        if m is not None:
            dr, along, off, branch_off = m
            out.matches[v.key] = Match(dr.id, along, off, branch_off)
    return out


def _unmatched_reason(v: Vehicle, static: Static) -> str:
    if v.line not in static.lines:
        return "unknown_line"
    if v.dest is None:
        return "no_destination"
    if "depo" in v.dest.lower() or v.dest.lower().startswith("dp."):
        return "to_depot"
    return "unknown_direction"


def line_view(line: str, snap: Snapshot, derived: Derived, static: Static, now: datetime) -> dict | None:
    info = static.lines.get(line)
    if info is None:
        return None
    on_line = [v for v in snap.vehicles if v.line == line]
    directions = []
    for d, dr in static.directions.get(line, {}).items():
        interval = static.scheduled_interval(line, d, now)
        speed = dr.length / dr.duration if dr.duration else None  # m/s along the route
        vehicles = []
        for v in on_line:
            m = derived.matches.get(v.key)
            if m is None or m.direction != d:
                continue
            vehicles.append(
                {
                    "key": v.key,
                    "along": round(m.along),
                    "offRoute": m.off > OFF_ROUTE_M and not m.on_branch,
                    # On a branch the vehicle's `along` is only its nearest point on the main route.
                    "onBranch": m.on_branch,
                    "delay": v.delay_s,
                    "stale": is_stale(v, snap, now),
                    "dest": v.dest,
                    "type": v.type,
                    "lastStop": static.stop_before(dr, m.along),
                }
            )
        vehicles.sort(key=lambda x: x["along"])
        # Gap from each vehicle to the next one ahead of it on the route.
        # Parked vehicles (depots beside the route, broken-down buses) aren't part of the service:
        # they stay in the list but get no gaps and don't count in the summary. Neither do vehicles
        # on a branch, whose position along the main route is only approximate.
        running = [x for x in vehicles if not x["offRoute"] and not x["onBranch"] and not x["stale"]]
        for behind, ahead in zip(running, running[1:]):
            dist = ahead["along"] - behind["along"]
            secs = round(dist / speed) if speed else None
            flag = None
            # Vehicles laying over at either terminus aren't running yet, so they don't count.
            in_service = behind["along"] > AT_START_M and ahead["along"] < dr.length - AT_START_M
            # The interval is measured at the reference stop. Before it, branches and trips that
            # start partway along haven't joined yet, so the spacing there isn't comparable.
            in_service = in_service and behind["along"] >= dr.stop_dist[dr.ref_stop]
            if interval and secs is not None and in_service:
                if secs > GAP_FACTOR * interval:
                    flag = "gap"
                elif secs < BUNCH_FACTOR * interval:
                    flag = "bunched"
            behind["gapAhead"] = {"m": dist, "s": secs, "flag": flag}

        delays = [x["delay"] for x in running if x["delay"] is not None]
        biggest = max(
            (x for x in running if x.get("gapAhead") and x["gapAhead"]["flag"] == "gap"),
            key=lambda x: x["gapAhead"]["s"],
            default=None,
        )
        directions.append(
            {
                "id": d,
                "headsign": dr.headsign,
                "from": static.stops[dr.stops[0]]["name"],
                "length": round(dr.length),
                "duration": dr.duration,
                "interval": interval,
                "coords": dr.coords,
                "branches": dr.branches,
                "stops": [
                    {
                        "id": s,
                        "name": static.stops[s]["name"],
                        "dist": round(dist),
                        "lat": static.stops[s]["lat"],
                        "lon": static.stops[s]["lon"],
                    }
                    for s, dist in zip(dr.stops, dr.stop_dist)
                ],
                "vehicles": vehicles,
                "summary": {
                    "count": len(running),
                    "medianDelay": int(statistics.median(delays)) if delays else None,
                    "gaps": sum(1 for x in running if x.get("gapAhead", {}).get("flag") == "gap"),
                    "bunched": sum(1 for x in running if x.get("gapAhead", {}).get("flag") == "bunched"),
                    # The biggest flagged gap: it lies between the last stop passed by the vehicle
                    # behind it (fromStop) and the last stop passed by the vehicle ahead (afterStop).
                    "biggestGap": {
                        "s": biggest["gapAhead"]["s"],
                        "fromStop": static.stops[dr.stops[biggest["lastStop"]]]["name"],
                        "afterStop": static.stops[dr.stops[_ahead_of(running, biggest)["lastStop"]]]["name"],
                    }
                    if biggest
                    else None,
                },
            }
        )
    unmatched = [
        {"key": v.key, "dest": v.dest, "reason": _unmatched_reason(v, static)}
        for v in on_line
        if v.key not in derived.matches
    ]
    return {
        "line": line,
        "type": info["type"],
        "color": info["color"],
        "textColor": info["textColor"],
        "directions": directions,
        "unmatched": unmatched,
    }


def _ahead_of(running: list[dict], x: dict) -> dict:
    return running[running.index(x) + 1]


def city_status(snap: Snapshot, derived: Derived, static: Static | None, now: datetime) -> dict:
    """Vehicles in service: with a line, not parked (stale), and not far from their route."""

    def running(v: Vehicle) -> bool:
        m = derived.matches.get(v.key)
        return v.line is not None and not is_stale(v, snap, now) and (m is None or m.off <= OFF_ROUTE_M or m.on_branch)

    in_service = [v for v in snap.vehicles if running(v)]
    by_type = Counter(v.type for v in in_service)
    with_delay = [v for v in in_service if v.delay_s is not None]
    late = [v for v in with_delay if v.delay_s >= LATE_S]
    per_line: dict[str, list[int]] = defaultdict(list)
    for v in with_delay:
        per_line[v.line].append(v.delay_s)
    worst = sorted(
        (
            {
                "line": line,
                "medianDelay": int(statistics.median(ds)),
                "vehicles": len(ds),
                "shareLate": round(sum(d >= LATE_S for d in ds) / len(ds), 3),
                "type": static.lines[line]["type"] if static and line in static.lines else None,
            }
            for line, ds in per_line.items()
            if len(ds) >= WORST_MIN_VEHICLES
        ),
        key=lambda x: (-x["medianDelay"], -x["shareLate"]),
    )[:5]
    return {
        "vehicles": len(in_service),
        "byType": dict(by_type),
        "withDelay": len(with_delay),
        "shareLate": round(len(late) / len(with_delay), 3) if with_delay else None,
        "worst": worst,
    }
