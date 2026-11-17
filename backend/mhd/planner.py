"""Journey planner: RAPTOR over the timetable patterns of data/static.

Rounds are rides (up to MAX_RIDES, i.e. four transfers). After each round, arrivals by vehicle
spread to stops within FOOT_M on foot, or stay at the stop with a short change time. The result
is the Pareto set over (arrival, transfers), topped up with later departures of the best option.

Times inside the search are seconds after the query day's service midnight (noon minus 12 h,
as in GTFS), so trips of yesterday's service day running after midnight appear with their times
minus one day and early trips of tomorrow with their times plus one day.
"""

from __future__ import annotations

import json
import math
from bisect import bisect_left
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .geo import Polyline, to_lonlat, to_xy

TZ = ZoneInfo("Europe/Bratislava")

MAX_RIDES = 5  # four transfers
WALK_SPEED = 1.25  # m/s
DETOUR = 1.3  # walking distance per metre crow-fly
FOOT_M = 400.0  # transfer walks between stops
ACCESS_M = 800.0  # walking to the first / from the last stop
ACCESS_WIDE_M = 1500.0  # … when nothing is within ACCESS_M
WALK_ONLY_M = 2000.0  # longest walk offered instead of transit
STATION_CHANGE_S = 60  # platform change within a station
SAME_STOP_CHANGE_S = 30  # changing vehicles at the same stop
REALTIME_BACKOFF_S = 1200  # with delays, look at trips scheduled up to 20 min before
SHAPE_MAX_OFF_M = 150.0  # a stop farther than this from a shape: draw its hops straight
SHAPE_DETOUR, SHAPE_DETOUR_M = 3.0, 300.0  # a hop's shape longer than 3 × crow-fly + 300 m: straight
TOMORROW_WINDOW_S = 6 * 3600  # tomorrow's trips starting before 06:00 are searchable
TRANSFER_SLACK_S = 120  # an extra transfer must save more than this to be offered
SAME_PLACE_M = 30.0  # origin and destination this close: nothing to plan
WALK_OFFER_M = 1200.0  # a walk this long is offered next to rides …
WALK_OFFER_SLOWER_S = 300  # … arriving up to this much later than the first of them
RISK_LATE_S = 60  # a transfer is at risk when the ride before it runs at least this late …
RISK_MARGIN_S = 180  # … and leaves less than this to spare (delays tend to grow)
INF = math.inf


def walk_seconds(dist_m: float) -> int:
    return int(math.ceil(dist_m * DETOUR / WALK_SPEED))


def _service_midnight(d: date) -> datetime:
    """Service day origin (noon minus 12 h) in UTC."""
    return datetime(d.year, d.month, d.day, 12, tzinfo=TZ).astimezone(UTC) - timedelta(hours=12)


def transfer_status(margin: float, feeder_delay: int | None) -> str:
    """"missed" when the change can't be made, "tight" when the ride before it is late and little
    time is left to spare, else "ok"."""
    if margin < 0:
        return "missed"
    if feeder_delay is not None and feeder_delay >= RISK_LATE_S and margin < RISK_MARGIN_S:
        return "tight"
    return "ok"


class _Day:
    """Active trips of one service day, per pattern sorted by departure at the first stop."""

    __slots__ = ("base", "cols", "trips", "backoff", "instances")

    def __init__(self, planner: "Planner", d: date):
        self.base = _service_midnight(d)
        per_pat: list[list[tuple[int, int, int]]] = [[] for _ in planner.pat_stops]
        for off in (-1, 0, 1):
            dd = d + timedelta(days=off)
            active = planner.active_services(dd)
            shift = int((_service_midnight(dd) - self.base).total_seconds())
            for ti, (_, p, svc, _, times) in enumerate(planner.trips):
                if svc not in active:
                    continue
                if off < 0 and times[-1] + shift < 0:
                    continue
                if off > 0 and times[0] >= TOMORROW_WINDOW_S:
                    continue
                per_pat[p].append((times[0] + shift, ti, shift))
        self.cols: list[list[list[int]]] = []
        self.trips: list[list[int]] = []  # global trip index per pattern trip
        self.backoff: list[int] = []  # 0 when trips never overtake each other
        self.instances: dict[str, list[tuple[int, int, int, int]]] = {}  # trip id → (p, j, first, last)
        for p, entries in enumerate(per_pat):
            entries.sort()
            n = len(planner.pat_stops[p])
            cols = [[planner.trips[ti][4][i] + sh for _, ti, sh in entries] for i in range(n)]
            fifo = all(all(a <= b for a, b in zip(c, c[1:])) for c in cols)
            self.cols.append(cols)
            self.trips.append([ti for _, ti, _ in entries])
            self.backoff.append(0 if fifo else REALTIME_BACKOFF_S)
            for j, (_, ti, _) in enumerate(entries):
                self.instances.setdefault(planner.trips[ti][0], []).append((p, j, cols[0][j], cols[-1][j]))


class Planner:
    def __init__(self, static_dir: Path):
        static_dir = Path(static_dir)
        load = lambda name: json.loads((static_dir / f"{name}.json").read_text())  # noqa: E731
        tt = load("timetable")
        self.stops_raw: dict = load("stops")
        self.stations: dict = load("stations")
        self.calendar: dict = load("service")["calendar"]
        self.lines: dict = load("lines")
        self.shapes: dict = load("shapes")
        bpath = static_dir / "branches.json"
        self.branches: dict = json.loads(bpath.read_text()) if bpath.exists() else {}

        self.stop_ids: list[str] = list(self.stops_raw)
        self.stop_idx = {sid: i for i, sid in enumerate(self.stop_ids)}
        self.stop_ll = [(float(s["lon"]), float(s["lat"])) for s in self.stops_raw.values()]
        self.stop_xy = [to_xy(lon, lat) for lon, lat in self.stop_ll]
        self.stop_station = [s.get("station") for s in self.stops_raw.values()]

        self.pat_line: list[str] = []
        self.pat_dir: list[str | None] = []
        self.pat_stops: list[list[int]] = []
        for pat in tt["patterns"]:
            self.pat_line.append(pat["line"])
            self.pat_dir.append(pat["dir"])
            self.pat_stops.append([self.stop_idx[s] for s in pat["stops"]])
        # (trip id, pattern, service, headsign, times)
        self.trips = [(t["id"], t["p"], t["svc"], t.get("head"), tuple(t["t"])) for t in tt["trips"]]
        del tt

        self.stop_pats: list[list[tuple[int, int]]] = [[] for _ in self.stop_ids]
        for p, stops in enumerate(self.pat_stops):
            for i, s in enumerate(stops[:-1]):  # nobody boards at the last stop
                self.stop_pats[s].append((p, i))

        # Transfer walks, via a grid of FOOT_M cells.
        grid: dict[tuple[int, int], list[int]] = {}
        for i, (x, y) in enumerate(self.stop_xy):
            grid.setdefault((int(x // FOOT_M), int(y // FOOT_M)), []).append(i)
        self.foot: list[list[tuple[int, int]]] = [[] for _ in self.stop_ids]
        for i, (x, y) in enumerate(self.stop_xy):
            cx, cy = int(x // FOOT_M), int(y // FOOT_M)
            for gx in (cx - 1, cx, cx + 1):
                for gy in (cy - 1, cy, cy + 1):
                    for j in grid.get((gx, gy), ()):
                        if j == i:
                            continue
                        dist = math.hypot(self.stop_xy[j][0] - x, self.stop_xy[j][1] - y)
                        if dist > FOOT_M:
                            continue
                        w = walk_seconds(dist)
                        st = self.stop_station[i]
                        if st is not None and st == self.stop_station[j]:
                            w = max(w, STATION_CHANGE_S)
                        self.foot[i].append((j, w))
            self.foot[i].sort()

        self._days: dict[date, _Day] = {}
        self._shape_cache: dict[tuple[str, str], list[Polyline]] = {}
        self._pat_proj: dict[int, list[tuple[list[float], list[float]]]] = {}

    # ---- calendar ---------------------------------------------------------------------------

    def active_services(self, d: date) -> set[str]:
        ds = d.strftime("%Y%m%d")
        out = set()
        for sid, c in self.calendar.items():
            on = bool(c["days"][d.weekday()]) and c["start"] <= ds <= c["end"]
            if ds in c.get("added", ()):
                on = True
            if ds in c.get("removed", ()):
                on = False
            if on:
                out.add(sid)
        return out

    def _day(self, d: date) -> _Day:
        day = self._days.get(d)
        if day is None:
            if len(self._days) >= 2:
                self._days.pop(next(iter(self._days)))
            day = self._days[d] = _Day(self, d)
        return day

    # ---- places -----------------------------------------------------------------------------

    def _stop_point(self, s: int) -> dict:
        raw = self.stops_raw[self.stop_ids[s]]
        return {"name": raw.get("name"), "lat": raw["lat"], "lon": raw["lon"], "stop": self.stop_ids[s],
                "station": raw.get("station"), "platform": raw.get("platform")}

    def _place(self, place: dict) -> tuple[dict, list[int] | None]:
        """The place as a point, and the platforms of a station (None for a map point)."""
        if place.get("station") is not None:
            code = str(place["station"])
            st = self.stations.get(code)
            if st is None:
                raise ValueError(f"unknown station {code}")
            plats = [self.stop_idx[s] for s in st["stops"] if s in self.stop_idx]
            return {"name": st["name"], "lat": st["lat"], "lon": st["lon"], "stop": None,
                    "station": code, "platform": None}, plats
        lat, lon = float(place["lat"]), float(place["lon"])
        return {"name": place.get("name"), "lat": lat, "lon": lon, "stop": None,
                "station": None, "platform": None}, None

    def _near(self, lon: float, lat: float) -> dict[int, tuple[int, float]]:
        """Stops within walking reach of a point: stop → (walk seconds, crow-fly metres)."""
        px, py = to_xy(lon, lat)
        dist = [(math.hypot(x - px, y - py), i) for i, (x, y) in enumerate(self.stop_xy)]
        for r in (ACCESS_M, ACCESS_WIDE_M):
            got = {i: (walk_seconds(d), d) for d, i in dist if d <= r}
            if got:
                return got
        return {}

    # ---- search -----------------------------------------------------------------------------

    def _earliest(self, day: _Day, p: int, i: int, t: float, pdl: dict[int, int], mind: int):
        """Earliest pattern trip leaving position i at realtime ≥ t: (j, delay) or None."""
        col = day.cols[p][i]
        back = REALTIME_BACKOFF_S if pdl else day.backoff[p]
        j = bisect_left(col, t - back)
        best, best_t = None, INF
        n = len(col)
        while j < n:
            sched = col[j]
            if sched + mind > best_t or (not pdl and not back and best is not None):
                break
            d = pdl.get(j, 0) if pdl else 0
            rt = sched + d
            if t <= rt < best_t:
                best, best_t = (j, d), rt
            j += 1
        return best

    def _raptor(self, day: _Day, src: dict, egress: dict, delays: dict[tuple[int, int], int], mind: int):
        N = len(self.stop_ids)
        ride = [[INF] * N]
        rpar: list[list] = [[None] * N]
        ready = [[INF] * N]
        qpar: list[list] = [[None] * N]
        for s, (t, par) in src.items():
            ready[0][s], qpar[0][s] = t, par
        pdls: dict[int, dict[int, int]] = {}
        for (p, j), d in delays.items():
            pdls.setdefault(p, {})[j] = d
        marked = set(src)
        tgt = INF
        station = self.stop_station
        for k in range(1, MAX_RIDES + 1):
            if not marked:
                break
            prev_ready = ready[k - 1]
            ride_k, rp = ride[k - 1][:], rpar[k - 1][:]
            queue: dict[int, int] = {}
            for s in marked:
                for p, i in self.stop_pats[s]:
                    if queue.get(p, 1 << 30) > i:
                        queue[p] = i
            improved: set[int] = set()
            for p in sorted(queue):
                cols = day.cols[p]
                if not cols[0]:
                    continue
                stops = self.pat_stops[p]
                n = len(stops)
                pdl = pdls.get(p, {})
                j, d, bpos, bt = -1, 0, -1, 0
                for i in range(queue[p], n):
                    s = stops[i]
                    if j >= 0:
                        a = cols[i][j] + d
                        bs = stops[bpos]
                        if (a < ride_k[s] and a < tgt and a > bt and s != bs
                                and (station[s] is None or station[s] != station[bs])):
                            ride_k[s] = a
                            rp[s] = (k, p, j, bpos, i, d)
                            improved.add(s)
                            if s in egress and a + egress[s] < tgt:
                                tgt = a + egress[s]
                    if i == n - 1:
                        break
                    r = prev_ready[s]
                    if r < INF and (j < 0 or r <= cols[i][j] + d):
                        e = self._earliest(day, p, i, r, pdl, mind)
                        if e is not None and (j < 0 or cols[i][e[0]] + e[1] < cols[i][j] + d):
                            j, d = e
                            bpos, bt = i, cols[i][j] + d
            ride.append(ride_k)
            rpar.append(rp)
            ready_k, qp = prev_ready[:], qpar[k - 1][:]
            marked = set()
            for s in sorted(improved):
                a = ride_k[s]
                c = a + SAME_STOP_CHANGE_S
                if c < ready_k[s]:
                    ready_k[s], qp[s] = c, ("stay", k)
                    marked.add(s)
                for nb, w in self.foot[s]:
                    c = a + w
                    if c < ready_k[nb] and c < tgt:
                        ready_k[nb], qp[nb] = c, ("walk", k, s, w)
                        marked.add(nb)
                        if nb in egress and c + egress[nb] < tgt:
                            tgt = c + egress[nb]
            ready.append(ready_k)
            qpar.append(qp)

        # Best arrival per round, by vehicle or by a transfer walk, then the egress walk.
        found = []
        for k in range(1, len(ride)):
            best = None
            for s, eg in sorted(egress.items()):
                if ride[k][s] + eg < (best[0] if best else INF):
                    best = (ride[k][s] + eg, s, "ride")
                q = qpar[k][s]
                if q is not None and q[0] == "walk" and ready[k][s] + eg < (best[0] if best else INF):
                    best = (ready[k][s] + eg, s, "ready")
            if best:
                found.append(self._path(best[1], k, best[2], rpar, qpar))
        return found

    def _path(self, s: int, k: int, kind: str, rpar, qpar) -> list[tuple]:
        """Steps from origin to stop s: ("access", via, s, w) | ("ride", p, j, b, a, d) | ("walk", a, b, w)."""
        steps: list[tuple] = []
        r = k
        while True:
            if kind == "ride":
                _, p, j, bpos, apos, d = rpar[r][s]
                rr = rpar[r][s][0]
                steps.append(("ride", p, j, bpos, apos, d))
                s, r, kind = self.pat_stops[p][bpos], rr - 1, "ready"
            else:
                q = qpar[r][s]
                if q[0] == "stay":
                    r, kind = q[1], "ride"
                elif q[0] == "walk":
                    steps.append(("walk", q[2], s, q[3]))
                    s, r, kind = q[2], q[1], "ride"
                else:
                    steps.append(("access", q[1], s, q[2]))
                    break
        steps.reverse()
        return steps

    # ---- output -----------------------------------------------------------------------------

    def _iso(self, day: _Day, t: float) -> str:
        return (day.base + timedelta(seconds=t)).astimezone(TZ).isoformat(timespec="seconds")

    def _candidate_shapes(self, p: int) -> list[Polyline]:
        line, dr = self.pat_line[p], self.pat_dir[p]
        if dr is None:
            return []
        key = (line, dr)
        if key not in self._shape_cache:
            cands = []
            main = self.shapes.get(line, {}).get(dr)
            if main and len(main) >= 2:
                cands.append(main)
            cands += [b for b in self.branches.get(line, {}).get(dr, []) if len(b) >= 2]
            self._shape_cache[key] = [Polyline([tuple(c) for c in cs]) for cs in cands]
        return self._shape_cache[key]

    def _projections(self, p: int) -> list[tuple[Polyline, list[float], list[float]]]:
        """Per candidate shape: along-distance and offset of each pattern stop, in order."""
        if p not in self._pat_proj:
            out = []
            for pl in self._candidate_shapes(p):
                along, off, lo = [], [], 0.0
                for s in self.pat_stops[p]:
                    a, dist = pl.project(*self.stop_ll[s], lo=lo)
                    along.append(a)
                    off.append(dist)
                    if dist <= SHAPE_MAX_OFF_M:
                        lo = a
                out.append((pl, along, off))
            self._pat_proj[p] = out
        return self._pat_proj[p]

    def _ride_coords(self, p: int, bpos: int, apos: int) -> list[list[float]]:
        """The ride along its shape, hop by hop: a hop follows the candidate shape that passes
        both its stops in order without a long detour, and is drawn straight when none does."""
        stops = self.pat_stops[p]
        projs = self._projections(p)
        pts: list[list[float]] = []

        def add_ll(lonlat: tuple[float, float]) -> None:
            pt = [round(lonlat[0], 6), round(lonlat[1], 6)]
            if not pts or pts[-1] != pt:
                pts.append(pt)

        def add(xy: tuple[float, float]) -> None:
            add_ll(to_lonlat(*xy))

        for i in range(bpos, apos):
            (ax, ay), (bx, by) = self.stop_xy[stops[i]], self.stop_xy[stops[i + 1]]
            crow = math.hypot(bx - ax, by - ay)
            best = None
            for pl, along, off in projs:
                worst = max(off[i], off[i + 1])
                a0, a1 = along[i], along[i + 1]
                if (worst <= SHAPE_MAX_OFF_M and a1 > a0 and a1 - a0 <= SHAPE_DETOUR * crow + SHAPE_DETOUR_M
                        and (best is None or worst < best[0])):
                    best = (worst, pl, a0, a1)
            if best is None:
                add_ll(self.stop_ll[stops[i]])
                add_ll(self.stop_ll[stops[i + 1]])
                continue
            _, pl, a0, a1 = best
            add(self._at(pl, a0))
            j = bisect_left(pl.cum, a0)
            while j < len(pl.cum) and pl.cum[j] <= a0:
                j += 1
            while j < len(pl.cum) and pl.cum[j] < a1:
                add(pl.xy[j])
                j += 1
            add(self._at(pl, a1))
        # The ride starts and ends at the platforms, so its line meets the walk legs even where a
        # stop stands off the street route (up to 150 m).
        if pts:
            first, last = self.stop_ll[stops[bpos]], self.stop_ll[stops[apos]]
            pts.insert(0, [round(first[0], 6), round(first[1], 6)])
            add_ll(last)
            if pts[0] == pts[1]:
                pts.pop(0)
        return pts

    @staticmethod
    def _at(pl: Polyline, a: float) -> tuple[float, float]:
        i = max(0, min(len(pl.cum) - 2, bisect_left(pl.cum, a) - 1))
        seg = pl.cum[i + 1] - pl.cum[i]
        f = 0.0 if seg <= 0 else (a - pl.cum[i]) / seg
        (ax, ay), (bx, by) = pl.xy[i], pl.xy[i + 1]
        return ax + f * (bx - ax), ay + f * (by - ay)

    def _build(self, day: _Day, steps: list[tuple], o_pt: dict, d_pt: dict, egress_m: dict,
               access_m: dict, delays: dict[tuple[int, int], int]) -> dict:
        legs: list[dict] = []
        t = None  # time at the end of the previous leg
        prev_ride: tuple[float, int | None] | None = None  # (arrival, live delay) of the last ride
        pending_walk: list[tuple] = []  # walk steps before the next ride: (from P, to P, w, m)

        def walk_leg(frm, to, start, end, m, via=None):
            coords = [[frm["lon"], frm["lat"]]] + (via or []) + [[to["lon"], to["lat"]]]
            return {"kind": "walk", "from": frm, "to": to, "start": self._iso(day, start),
                    "end": self._iso(day, end), "m": int(round(m)), "coords": coords}

        def flush(end_time=None):
            """Merge pending walks into one leg; before a ride it ends at the boarding time."""
            nonlocal t
            if not pending_walk:
                return
            frm, to = pending_walk[0][0], pending_walk[-1][1]
            w = sum(x[2] for x in pending_walk)
            m = sum(x[3] for x in pending_walk)
            via = [[x[1]["lon"], x[1]["lat"]] for x in pending_walk[:-1]]
            if t is None:  # first leg: leave just in time
                start, end = end_time - w, end_time
            else:
                start, end = t, t + w
            pending_walk.clear()
            if frm.get("stop") is not None and frm.get("stop") == to.get("stop"):
                t = end
                return
            legs.append(walk_leg(frm, to, start, end, m, via))
            t = end

        for st in steps:
            if st[0] == "access":
                _, via, s, w = st
                if via is None:
                    if access_m:  # walk from a map point
                        pending_walk.append((o_pt, self._stop_point(s), w, access_m[s] * DETOUR))
                else:  # walk from a station platform to a nearby stop
                    dist = math.hypot(self.stop_xy[s][0] - self.stop_xy[via][0],
                                      self.stop_xy[s][1] - self.stop_xy[via][1])
                    pending_walk.append((self._stop_point(via), self._stop_point(s), w, dist * DETOUR))
            elif st[0] == "walk":
                _, a, b, w = st
                dist = math.hypot(self.stop_xy[a][0] - self.stop_xy[b][0], self.stop_xy[a][1] - self.stop_xy[b][1])
                pending_walk.append((self._stop_point(a), self._stop_point(b), w, dist * DETOUR))
            else:
                _, p, j, bpos, apos, d = st
                cols = day.cols[p]
                bt, at = cols[bpos][j] + d, cols[apos][j] + d
                live_d = d if (p, j) in delays else None
                transfer = None
                if prev_ride is not None:
                    # Time to spare: the change walk (or the same-stop change) against the departure.
                    need = sum(x[2] for x in pending_walk) if pending_walk else SAME_STOP_CHANGE_S
                    margin = int(bt - prev_ride[0] - need)
                    transfer = {"margin": margin, "status": transfer_status(margin, prev_ride[1]), "fallback": None}
                flush(bt)
                ti = day.trips[p][j]
                tid, _, _, head, _ = self.trips[ti]
                line = self.pat_line[p]
                info = self.lines.get(line, {})
                stops = self.pat_stops[p]
                legs.append({
                    "kind": "ride", "line": line, "type": info.get("type"), "color": info.get("color"),
                    "textColor": info.get("textColor"), "dir": self.pat_dir[p], "headsign": head, "trip": tid,
                    "from": self._stop_point(stops[bpos]), "to": self._stop_point(stops[apos]),
                    "start": self._iso(day, bt), "end": self._iso(day, at), "delay": live_d, "transfer": transfer,
                    "stops": [{"stop": self.stop_ids[stops[i]], "name": self.stops_raw[self.stop_ids[stops[i]]].get("name"),
                               "lat": self.stop_ll[stops[i]][1], "lon": self.stop_ll[stops[i]][0],
                               "time": self._iso(day, cols[i][j] + d)} for i in range(bpos, apos + 1)],
                    "coords": self._ride_coords(p, bpos, apos),
                })
                t = at
                prev_ride = (at, live_d)
        # Egress to the destination.
        last = legs[-1]["to"] if legs else o_pt
        if egress_m and last.get("stop") is not None:
            s = self.stop_idx[last["stop"]]
            if pending_walk:
                s = self.stop_idx[pending_walk[-1][1]["stop"]]
            pending_walk.append((self._stop_point(s), d_pt, walk_seconds(egress_m[s]), egress_m[s] * DETOUR))
        flush()
        return self._summary(day, legs)

    def _summary(self, day: _Day, legs: list[dict]) -> dict:
        dep = datetime.fromisoformat(legs[0]["start"])
        arr = datetime.fromisoformat(legs[-1]["end"])
        rides = sum(1 for leg in legs if leg["kind"] == "ride")
        return {"depart": legs[0]["start"], "arrive": legs[-1]["end"],
                "duration": int((arr - dep).total_seconds()), "transfers": max(0, rides - 1),
                "walkM": sum(leg["m"] for leg in legs if leg["kind"] == "walk"), "legs": legs}

    # ---- public -----------------------------------------------------------------------------

    def plan(self, origin: dict, dest: dict, depart: datetime, delays: dict[str, int] | None = None,
             max_results: int = 3) -> list[dict]:
        return self.plan_with_reason(origin, dest, depart, delays, max_results)[0]

    def plan_with_reason(self, origin: dict, dest: dict, depart: datetime, delays: dict[str, int] | None = None,
                         max_results: int = 3) -> tuple[list[dict], str | None]:
        """Options, and why there are none: "same_place", "no_stops_near_origin",
        "no_stops_near_destination" or "no_connection" (None when there are options)."""
        if depart.tzinfo is None:
            depart = depart.replace(tzinfo=TZ)
        local = depart.astimezone(TZ)
        day = self._day(local.date())
        t0 = int(math.floor((depart.astimezone(UTC) - day.base).total_seconds()))

        o_pt, o_plats = self._place(origin)
        d_pt, d_plats = self._place(dest)
        dist = math.hypot(*(a - b for a, b in zip(to_xy(o_pt["lon"], o_pt["lat"]), to_xy(d_pt["lon"], d_pt["lat"]))))
        if (o_pt["station"] is not None and o_pt["station"] == d_pt["station"]) or dist < SAME_PLACE_M:
            return [], "same_place"

        results, reason = self._rides(o_pt, o_plats, d_pt, d_plats, depart, delays, max_results)
        if reason == "no_connection":  # nothing more today: the next service day from its start
            nxt = _service_midnight(local.date() + timedelta(days=1))
            results, _ = self._rides(o_pt, o_plats, d_pt, d_plats, nxt, None, max_results)

        # Walking all the way: when it beats every ride, or is short and not much slower. Rides
        # taking at least as long as the walk are then left out.
        if 0 < dist <= WALK_ONLY_M:
            w = walk_seconds(dist)
            arrive = depart.timestamp() + w
            best = min((it["arrive_t"] for it in results), default=INF)
            if arrive < best or (dist * DETOUR <= WALK_OFFER_M and arrive <= best + WALK_OFFER_SLOWER_S):
                leg = {"kind": "walk", "from": o_pt, "to": d_pt, "start": self._iso(day, t0),
                       "end": self._iso(day, t0 + w), "m": int(round(dist * DETOUR)),
                       "coords": [[o_pt["lon"], o_pt["lat"]], [d_pt["lon"], d_pt["lat"]]]}
                walk = {**self._summary(day, [leg]), "arrive_t": arrive}
                results = sorted([it for it in results if it["duration"] < w] + [walk], key=lambda it: it["arrive_t"])
                if walk not in results[:max_results]:
                    results = results[:max_results - 1] + [walk]
        for it in results:
            it.pop("depart_t", None)
            it.pop("arrive_t", None)
        results = results[:max_results]
        for it in results:
            self._add_fallbacks(it, d_pt, d_plats, delays)
        return results, (None if results else reason)

    def track(self, origin: dict, dest: dict, rides: list[tuple[str, str, str]], now: datetime,
              delays: dict[str, int] | None = None) -> dict | None:
        """An itinerary given by its rides (trip id, boarding stop, alighting stop), rebuilt for the
        trip instances running around now with current delays, so a transfer it no longer makes
        shows as "missed" with a fallback. None when a ride can't be found."""
        if now.tzinfo is None:
            now = now.replace(tzinfo=TZ)
        o_pt, o_plats = self._place(origin)
        d_pt, d_plats = self._place(dest)
        day = self._day(now.astimezone(TZ).date())
        t0 = int(math.floor((now.astimezone(UTC) - day.base).total_seconds()))
        dl = self._instance_delays(day, t0, delays)
        steps: list[tuple] = []
        access_m: dict[int, float] = {}
        egress_m: dict[int, float] = {}
        t_ref, prev_a = t0, None
        for tid, fs, ts in rides:
            b, a = self.stop_idx.get(fs), self.stop_idx.get(ts)
            if b is None or a is None:
                return None
            best = None
            for p, j, _, _ in day.instances.get(tid, ()):
                stops = self.pat_stops[p]
                if b not in stops or a not in stops[stops.index(b) + 1:]:
                    continue
                bpos = stops.index(b)
                apos = stops.index(a, bpos + 1)
                gap = abs(day.cols[p][bpos][j] - t_ref)
                if best is None or gap < best[0]:
                    best = (gap, p, j, bpos, apos)
            if best is None or best[0] > 6 * 3600:
                return None
            _, p, j, bpos, apos = best
            if prev_a is None:
                if o_plats is None:
                    access_m[b] = self._dist_pt(b, o_pt)
                    steps.append(("access", None, b, walk_seconds(access_m[b])))
                elif b in o_plats:
                    steps.append(("access", None, b, 0))
                else:
                    via = min(o_plats, key=lambda q: self._dist(q, b))
                    steps.append(("access", via, b, self._walk_w(via, b)))
            elif prev_a != b:
                steps.append(("walk", prev_a, b, self._walk_w(prev_a, b)))
            steps.append(("ride", p, j, bpos, apos, dl.get((p, j), 0)))
            t_ref, prev_a = day.cols[p][apos][j], a
        if prev_a is None:
            return None
        if d_plats is None:
            egress_m[prev_a] = self._dist_pt(prev_a, d_pt)
        elif prev_a not in d_plats:
            q = min(d_plats, key=lambda q: self._dist(prev_a, q))
            steps.append(("walk", prev_a, q, self._walk_w(prev_a, q)))
        it = self._build(day, steps, o_pt, d_pt, egress_m, access_m, dl)
        self._add_fallbacks(it, d_pt, d_plats, delays)
        return it

    def _add_fallbacks(self, it: dict, d_pt: dict, d_plats: list[int] | None, delays: dict[str, int] | None) -> None:
        """For each transfer at risk or missed: the earliest way on from the stop where the ride
        before it arrives, once the connecting ride has left (or on arrival, if that is later)."""
        prev = None
        for leg in it["legs"]:
            if leg["kind"] != "ride":
                continue
            tr = leg.get("transfer")
            if prev is not None and tr and tr["status"] != "ok":
                s = self.stop_idx[prev["to"]["stop"]]
                start = max(datetime.fromisoformat(prev["end"]),
                            datetime.fromisoformat(leg["start"]) + timedelta(seconds=1))
                res, _ = self._rides(self._stop_point(s), [s], d_pt, d_plats, start, delays, 1)
                if res:
                    best = min(res, key=lambda x: (x["arrive_t"], x["transfers"]))
                    fb = {k: v for k, v in best.items() if k not in ("depart_t", "arrive_t")}
                    fb["legs"] = [{k: v for k, v in lg.items() if k not in ("coords", "stops", "transfer")}
                                  for lg in fb["legs"]]
                    tr["fallback"] = fb
            prev = leg

    def _dist(self, a: int, b: int) -> float:
        return math.hypot(self.stop_xy[a][0] - self.stop_xy[b][0], self.stop_xy[a][1] - self.stop_xy[b][1])

    def _dist_pt(self, s: int, pt: dict) -> float:
        x, y = to_xy(pt["lon"], pt["lat"])
        return math.hypot(self.stop_xy[s][0] - x, self.stop_xy[s][1] - y)

    def _walk_w(self, a: int, b: int) -> int:
        """The transfer walk the search uses between two stops (or a plain walk when farther)."""
        for nb, w in self.foot[a]:
            if nb == b:
                return w
        return walk_seconds(self._dist(a, b))

    @staticmethod
    def _instance_delays(day: _Day, t0: int, delays: dict[str, int] | None) -> dict[tuple[int, int], int]:
        """Delays of the trip instances running around t0, by (pattern, pattern trip)."""
        dl: dict[tuple[int, int], int] = {}
        for tid, d in (delays or {}).items():
            if d is None:
                continue
            inst = day.instances.get(tid)
            if not inst:
                continue
            gap, p, j = min((max(0, first - t0, t0 - last), p, j) for p, j, first, last in inst)
            if gap <= 3 * 3600:
                dl[(p, j)] = int(d)
        return dl

    def _rides(self, o_pt: dict, o_plats: list[int] | None, d_pt: dict, d_plats: list[int] | None,
               depart: datetime, delays: dict[str, int] | None, max_results: int) -> tuple[list[dict], str | None]:
        """Transit options (with "depart_t" and "arrive_t" timestamps), and the reason when none."""
        local = depart.astimezone(TZ)
        day = self._day(local.date())
        t0 = int(math.floor((depart.astimezone(UTC) - day.base).total_seconds()))

        # Access: a station's platforms at once (and stops a transfer walk away), or a walk.
        access_m: dict[int, float] = {}
        src: dict[int, tuple[float, tuple]] = {}
        if o_plats is not None:
            for s in o_plats:
                src[s] = (t0, ("access", None, 0))
            for s in o_plats:
                for nb, w in self.foot[s]:
                    if t0 + w < src.get(nb, (INF,))[0]:
                        src[nb] = (t0 + w, ("access", s, w))
        else:
            for s, (w, dist) in self._near(o_pt["lon"], o_pt["lat"]).items():
                src[s] = (t0 + w, ("access", None, w))
                access_m[s] = dist
        egress_m: dict[int, float] = {}
        if d_plats is not None:
            egress = {s: 0 for s in d_plats}
        else:
            egress = {}
            for s, (w, dist) in self._near(d_pt["lon"], d_pt["lat"]).items():
                egress[s], egress_m[s] = w, dist

        dl = self._instance_delays(day, t0, delays)
        mind = min([0, *dl.values()])

        def search(t: float) -> list[dict]:
            src_t = {s: (v[0] - t0 + t, v[1]) for s, v in src.items()}
            out = []
            for steps in self._raptor(day, src_t, egress, dl, mind):
                if not any(st[0] == "ride" for st in steps):
                    continue
                out.append(self._build(day, steps, o_pt, d_pt, egress_m, access_m, dl))
            return out

        def sig(it: dict) -> tuple:
            return tuple((leg["trip"], leg["from"]["stop"], leg["to"]["stop"]) for leg in it["legs"]
                         if leg["kind"] == "ride")

        def key(it: dict) -> tuple:
            return (it["arrive_t"], it["transfers"], -it["depart_t"], it["walkM"], sig(it))

        cands: dict[tuple, dict] = {}

        def add(its: list[dict]) -> None:
            for it in its:
                it["depart_t"] = datetime.fromisoformat(it["depart"]).timestamp()
                it["arrive_t"] = datetime.fromisoformat(it["arrive"]).timestamp()
                k = sig(it)
                if k not in cands or key(it) < key(cands[k]):
                    cands[k] = it

        def pareto() -> list[dict]:
            its = sorted(cands.values(), key=key)
            keep = []
            for a in its:
                dominated = any(
                    b is not a and (
                        # Strictly Pareto-dominated, counting a later departure as better …
                        (b["arrive_t"] <= a["arrive_t"] and b["transfers"] <= a["transfers"]
                         and b["depart_t"] >= a["depart_t"]
                         and (b["arrive_t"], b["transfers"], -b["depart_t"])
                         != (a["arrive_t"], a["transfers"], -a["depart_t"]))
                        # … or an extra transfer that saves less than TRANSFER_SLACK_S.
                        or (b["transfers"] < a["transfers"] and b["depart_t"] >= a["depart_t"] - TRANSFER_SLACK_S
                            and b["arrive_t"] <= a["arrive_t"] + TRANSFER_SLACK_S * (a["transfers"] - b["transfers"])))
                    for b in its)
                if not dominated and all((b["arrive_t"], b["transfers"], b["depart_t"]) !=
                                         (a["arrive_t"], a["transfers"], a["depart_t"]) for b in keep):
                    keep.append(a)
            return keep

        # Later departures of the best option of each run, until there are enough results.
        t = t0
        if not src or not egress:
            return [], "no_stops_near_origin" if not src else "no_stops_near_destination"
        last = search(t)
        add(last)
        runs = 1
        while last and len(pareto()) < max_results and runs < 3 * max_results + 2:
            best = min(last, key=key)
            t = max(t + 1, best["depart_t"] - depart.timestamp() + t0 + 1)
            last = search(t)
            add(last)
            runs += 1
        results = pareto()
        return results, None if results else "no_connection"
