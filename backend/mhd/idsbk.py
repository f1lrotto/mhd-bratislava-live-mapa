"""IDS BK regional buses: their timetable for the static build, and their live positions.

Timetable: IDS BK publishes it as GTFS in a Google Drive folder without a stable URL; the transiq
project (github.com/xhyrom/transiq) mirrors the newest file daily at a fixed one. The build caches
the last good download and uses it when the mirror fails.

Live positions come from the IDS BK map (mapa.idsbk.sk, run on Ubian). Its endpoint is
undocumented and returns the CAP vehicles nearest a point, whatever radius is asked (above about
30 km it returns none). Around Bratislava those are mostly DPB's trams and trolleybuses, so one
sweep queries a quadtree of tiles over AREA: a tile whose CAP vehicles don't reach its corners is
split into four for the rest of the sweep and for later sweeps, and every RESET_S the sweep starts
again from one tile so the tiles split for the rush hour merge back. Requests are at least
MIN_GAP_S apart, and a sweep starts SWEEP_S after the last one started (or right after it, when
it took longer). Measured 17 Nov 2026 at 16:30: 33 requests to start from one tile, 25 leaf
tiles after it, 120 regional buses.

A record (most fields left out):
{"vehicleID":806137625,"delayMinutes":0,"latitude":48.29086,"longitude":17.21731,
 "timeTableTrip":{"tripID":806137625,"trip":14,"destination":"Bratislava, Nám. A. Hlinku",
  "timeTableLine":{"line":"531","ezIsTrain":false,"ezIsUrban":false},
  "operatorName":"ARRIVA Mobility Solutions"},"licenseNumber":null,"lastCommunication":"0001-01-01T00:00:00"}

The vehicle id is the trip's id, and records have no timestamp and no fleet number: a bus that
starts its next trip is a new vehicle. `trip` is the trip number, GTFS trip_short_name; odd
numbers run one way and even the other.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import math
import os
import time
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Awaitable, Callable

import httpx

from .feed import REGIONAL, Vehicle
from .geo import Polyline
from .poller import distance_m

log = logging.getLogger(__name__)

GTFS_URL = os.environ.get("MHD_IDSBK_GTFS_URL", "https://transiq.xhyrom.dev/gtfs/sk/ids-bk_regional.zip")
URL = os.environ.get("MHD_IDSBK_URL", "https://mapa.idsbk.sk/navigation/vehicles/nearby")

# lat0, lat1, lon0, lon1: every stop of the regional GTFS (Rajka to Borský Svätý Jur, Záhorská
# Ves to Veľké Úľany, Nov 2026). The build warns when a stop falls outside.
AREA = (47.97, 48.64, 16.82, 17.61)
CAP = 100  # vehicles per response
RADIUS_M = 20_000
FREE_REACH_M = 25_000  # a response with fewer than CAP vehicles has every vehicle this close
MIN_HALF_M = 1_500  # tiles this small (centre to corner) are never split
SWEEP_S = 30
MIN_GAP_S = 1.0
MAX_REQUESTS = 60  # a sweep needing more fails rather than flood the endpoint
RESET_S = 600
MAX_BACKOFF_S = 600

Tile = tuple[float, float, float, float]  # lat0, lat1, lon0, lon1


class SweepError(Exception):
    pass


# --- timetable --------------------------------------------------------------------------------


def gtfs_version(zip_bytes: bytes) -> str:
    """A hash of the feed's tables (it has no feed_info), stable across re-zipping."""
    h = hashlib.sha256()
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        for name in sorted(n for n in z.namelist() if n.endswith(".txt")):
            h.update(name.encode())
            h.update(z.read(name))
    return h.hexdigest()[:16]


def prepare(gtfs: dict, taken_lines: set[str] = frozenset()) -> tuple[dict, Callable, dict[str, dict]]:
    """The regional GTFS made ready for build.build next to DPB's:

    - stop, trip, route and service ids get the REGIONAL prefix; line numbers stay as they are
      (5xx–9xx, none of DPB's), and lines DPB also has (`taken_lines`) are left out;
    - stops sharing a name are the platforms of one station, whose code is REGIONAL plus the
      smallest stop id;
    - the feed has no direction_id, so odd trip numbers are direction 0 and even ones 1.

    Also returns the router build.build draws patterns with (along the feed's own shapes, which
    follow the roads) and each line's operator."""
    p = REGIONAL
    names: dict[str, list[str]] = defaultdict(list)
    for s in gtfs["stops"]:
        names[s["stop_name"].strip()].append(s["stop_id"])
    station = {sid: p + min(ids) for ids in names.values() for sid in ids}
    stops = [
        {**s, "stop_id": p + s["stop_id"], "stop_code": station[s["stop_id"]], "stop_name": s["stop_name"].strip()}
        for s in gtfs["stops"]
    ]
    for s in stops:
        lat, lon = float(s["stop_lat"]), float(s["stop_lon"])
        if not (AREA[0] <= lat <= AREA[1] and AREA[2] <= lon <= AREA[3]):
            log.warning("regional stop %s (%s) is outside the swept area", s["stop_id"], s["stop_name"])

    agencies = {a.get("agency_id", ""): a.get("agency_name") for a in gtfs.get("agency", [])}
    routes = [{**r, "route_id": p + r["route_id"]} for r in gtfs["routes"] if r["route_short_name"] not in taken_lines]
    for line in sorted({r["route_short_name"] for r in gtfs["routes"]} & set(taken_lines)):
        log.warning("regional line %s has the number of a DPB line; left out", line)
    operator = {r["route_short_name"]: {"operator": agencies.get(r.get("agency_id", ""))} for r in routes}

    def direction(t: dict) -> str:
        if t.get("direction_id"):
            return t["direction_id"]
        no = t.get("trip_short_name", "")
        return "0" if not no.isdigit() or int(no) % 2 else "1"

    trips = [
        {**t, "trip_id": p + t["trip_id"], "route_id": p + t["route_id"], "service_id": p + t["service_id"], "direction_id": direction(t)}
        for t in gtfs["trips"]
    ]
    stop_times = [{**st, "trip_id": p + st["trip_id"], "stop_id": p + st["stop_id"]} for st in gtfs["stop_times"]]
    out = {
        "feed_info": [],
        "routes": routes,
        "trips": trips,
        "stops": stops,
        "stop_times": stop_times,
        "calendar": [{**c, "service_id": p + c["service_id"]} for c in gtfs["calendar"]],
        "calendar_dates": [{**c, "service_id": p + c["service_id"]} for c in gtfs["calendar_dates"]],
    }
    return out, _shape_router(out, gtfs.get("shapes", [])), operator


def _shape_router(gtfs: dict, shapes: list[dict]) -> Callable:
    pts: dict[str, list[tuple[int, float, float]]] = defaultdict(list)
    for r in shapes:
        pts[r["shape_id"]].append((int(r["shape_pt_sequence"]), float(r["shape_pt_lon"]), float(r["shape_pt_lat"])))
    coords = {sid: [(lon, lat) for _, lon, lat in sorted(v)] for sid, v in pts.items()}
    lonlat = {s["stop_id"]: (float(s["stop_lon"]), float(s["stop_lat"])) for s in gtfs["stops"]}

    seq: dict[str, list[tuple[int, str, float | None]]] = defaultdict(list)
    for st in gtfs["stop_times"]:
        sdt = st.get("shape_dist_traveled")
        seq[st["trip_id"]].append((int(st["stop_sequence"]), st["stop_id"], float(sdt) if sdt else None))
    # Each stop pattern's most common shape, and the stops' distances along it from one of its trips.
    by_pattern: dict[tuple[str, ...], Counter] = defaultdict(Counter)
    sdt_of: dict[tuple[tuple[str, ...], str], list[float | None]] = {}
    for t in gtfs["trips"]:
        s = sorted(seq.get(t["trip_id"], ()))
        pattern = tuple(x[1] for x in s)
        by_pattern[pattern][t.get("shape_id", "")] += 1
        sdt_of.setdefault((pattern, t.get("shape_id", "")), [x[2] for x in s])

    def route(line: str, mode: str, stops: tuple[str, ...]) -> tuple[list, list[float], int]:
        shape = by_pattern[stops].most_common(1)[0][0] if by_pattern.get(stops) else None
        line_pts = coords.get(shape) if shape else None
        stop_pts = [lonlat[s] for s in stops]
        if not line_pts or len(line_pts) < 2:  # no shape: straight from stop to stop
            return stop_pts, list(Polyline(stop_pts).cum), len(stops) - 1
        poly = Polyline(line_pts)
        return line_pts, _stop_dist(poly, stop_pts, sdt_of[(stops, shape)]), 0

    return route


def _stop_dist(poly: Polyline, stop_pts: list[tuple[float, float]], sdt: list[float | None]) -> list[float]:
    """Each stop's distance along the shape. The feed's shape_dist_traveled tells which pass of the
    shape a stop is on (shapes pass some stops twice); the projection on our own geometry gives
    the distance vehicles are measured with."""
    scale = poly.length / sdt[-1] if sdt and None not in sdt and sdt[-1] > 0 else None
    out: list[float] = []
    prev = 0.0
    for i, (lon, lat) in enumerate(stop_pts):
        along, off = (math.inf, math.inf)
        if scale is not None:
            along, off = poly.project(lon, lat, lo=max(prev, sdt[i] * scale - 500), hi=sdt[i] * scale + 500)
        if off == math.inf:
            along, _ = poly.project(lon, lat, lo=prev)
        prev = max(prev, along)
        out.append(prev)
    return out


# --- live positions ---------------------------------------------------------------------------


def _clean(s: object) -> str | None:
    s = str(s).strip() if s is not None else ""
    return s or None


def parse_vehicle(r: dict) -> Vehicle | None:
    """A regional bus, or None for city transport, trains and malformed records."""
    try:
        trip = r["timeTableTrip"]
        line = trip["timeTableLine"]
        if line.get("ezIsUrban") or line.get("ezIsTrain"):
            return None
        lat, lon = float(r["latitude"]), float(r["longitude"])
        no = int(trip["trip"]) if trip.get("trip") is not None else None
        d = r.get("delayMinutes")
        delay = int(d) * 60 if d is not None else None
        vid = r["vehicleID"]
    except (KeyError, TypeError, ValueError):
        return None
    if vid is None or (lat == 0 and lon == 0):
        return None
    return Vehicle(
        key=f"{REGIONAL}{vid}",
        line=_clean(line.get("line")),
        dest=_clean(trip.get("destination")),
        type="bus",
        lat=round(lat, 6),
        lon=round(lon, 6),
        delay_s=delay,
        state=None,
        azimuth=None,
        trip_no=no,
    )


async def fetch_nearby(client: httpx.AsyncClient, lat: float, lon: float) -> list[dict]:
    """The raw records of the CAP vehicles nearest a point, of every operator."""
    resp = await client.get(URL, params={"lat": f"{lat:.5f}", "lng": f"{lon:.5f}", "radius": RADIUS_M, "cityID": ""})
    if resp.status_code != 200:
        raise SweepError(f"HTTP {resp.status_code}")
    try:
        payload = resp.json()
    except ValueError as e:
        raise SweepError(f"invalid JSON: {e}") from e
    if not isinstance(payload, dict) or payload.get("status") != "ok" or not isinstance(payload.get("vehicles"), list):
        raise SweepError(f"unexpected payload: {str(payload)[:200]}")
    return payload["vehicles"]


def _centre(t: Tile) -> tuple[float, float]:
    return (t[0] + t[1]) / 2, (t[2] + t[3]) / 2


def _covered(t: Tile, raw: list[dict]) -> bool:
    """Whether one response holds every vehicle in its tile."""
    lat, lon = _centre(t)
    half = distance_m(lat, lon, t[1], t[3])
    if half <= MIN_HALF_M:
        return True
    if len(raw) < CAP:
        return half <= FREE_REACH_M
    reach = max(
        (distance_m(lat, lon, r["latitude"], r["longitude"]) for r in raw if isinstance(r.get("latitude"), (int, float)) and isinstance(r.get("longitude"), (int, float))),
        default=0.0,
    )
    return reach >= half


def _split(t: Tile) -> list[Tile]:
    lat, lon = _centre(t)
    return [(t[0], lat, t[2], lon), (t[0], lat, lon, t[3]), (lat, t[1], t[2], lon), (lat, t[1], lon, t[3])]


class Sweeper:
    """Sweeps the area every SWEEP_S and hands each result to `on_result(ts, vehicles, error)`:
    the regional buses (None when the sweep failed) at `ts`, the sweep's end."""

    def __init__(
        self,
        logger,
        on_result: Callable[[datetime, list[Vehicle] | None, str | None], None],
        fetch: Callable[[httpx.AsyncClient, float, float], Awaitable[list[dict]]] = fetch_nearby,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self.logger = logger
        self.on_result = on_result
        self._fetch = fetch
        self._sleep = sleep
        self._tiles: list[Tile] | None = None
        self._tiles_at = 0.0
        self.requests = 0  # requests of the last sweep

    async def sweep(self, client: httpx.AsyncClient | None) -> list[Vehicle]:
        now = time.monotonic()
        if self._tiles is None or now - self._tiles_at > RESET_S:
            self._tiles, self._tiles_at = [AREA], now
        queue = list(self._tiles)
        leaves: list[Tile] = []
        seen: dict[object, dict] = {}
        self.requests = 0
        t0 = time.monotonic()
        while queue:
            if self.requests >= MAX_REQUESTS:
                self._tiles = None
                raise SweepError(f"more than {MAX_REQUESTS} requests needed")
            wait = t0 + self.requests * MIN_GAP_S - time.monotonic()
            if wait > 0:
                await self._sleep(wait)
            tile = queue.pop(0)
            raw = await self._fetch(client, *_centre(tile))
            self.requests += 1
            for r in raw:
                if isinstance(r, dict):
                    seen.setdefault(r.get("vehicleID"), r)
            if _covered(tile, raw):
                leaves.append(tile)
            else:
                queue.extend(_split(tile))
        self._tiles = leaves
        return [v for r in seen.values() if (v := parse_vehicle(r)) is not None]

    async def sweep_once(self, client: httpx.AsyncClient | None) -> bool:
        t0 = time.monotonic()
        vehicles: list[Vehicle] | None = None
        error: str | None = None
        try:
            vehicles = await self.sweep(client)
        except Exception as e:  # any failure, including a changed format, is a logged outage
            error = f"{type(e).__name__}: {e}"[:500]
            log.warning("regional sweep failed after %d requests: %s", self.requests, error)
        ts = datetime.now(timezone.utc)
        duration_ms = int((time.monotonic() - t0) * 1000)
        if self.logger is not None:
            await asyncio.to_thread(self.logger.log_sweep, ts, vehicles, self.requests, duration_ms, error)
        try:
            self.on_result(ts, vehicles, error)
        except Exception:
            log.exception("on_result failed")
        return vehicles is not None

    async def run(self) -> None:
        headers = {"User-Agent": "mhd-nazivo/0.1 (single server poller, one sweep every 30 s)", "X-Requested-With": "XMLHttpRequest"}
        async with httpx.AsyncClient(timeout=12, headers=headers) as client:
            fails = 0
            while True:
                t0 = time.monotonic()
                try:
                    ok = await self.sweep_once(client)
                except Exception:
                    log.exception("unexpected sweep error")
                    ok = False
                fails = 0 if ok else fails + 1
                # A sweep already takes about SWEEP_S; after failures, back off.
                pause = SWEEP_S if ok else min(MAX_BACKOFF_S, SWEEP_S * 2**fails)
                await asyncio.sleep(max(0.0, t0 + pause - time.monotonic()))
