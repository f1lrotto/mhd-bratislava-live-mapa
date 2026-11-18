"""HTTP API and static file server.

Environment:
  MHD_DATA_DIR      where logs and the static build live (default: ../data next to backend/)
  MHD_NO_POLL=1     don't start the poller or the nightly jobs (tests, frontend work against a fixture)
  MHD_NO_REGIONAL=1 don't sweep the IDS BK map for regional buses (DPB's poller still runs)
  MHD_BASIC_AUTH    "user:password" to put everything behind HTTP basic auth while v1 is private
  RAILWAY_ENVIRONMENT_NAME=production (set by Railway) sends feed heartbeats to PostHog (heartbeat.py)

Run a single worker (no `--workers N`): the poller and logger live in the process, and DPB
must see one client.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import secrets
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import derive, heartbeat, idsbk, lineview, nightly, replay
from .history import History
from .logger import PollLogger
from .planner import DETOUR, MAX_RIDES, WALK_ONLY_M, WALK_SPEED, Planner
from .poller import Poller
from .reliability import KINDS, Reliability
from .speeds import Speeds
from .static import TZ, Static
from .stopevents import StopEventTracker

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("MHD_DATA_DIR", ROOT / "data"))
FRONTEND_DIR = ROOT / "frontend" / "dist"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def create_app(poller: Poller | None = None, start_polling: bool | None = None) -> FastAPI:
    if start_polling is None:
        start_polling = os.environ.get("MHD_NO_POLL") != "1"
    if poller is None:
        poller = Poller(PollLogger(DATA_DIR / "logs") if start_polling else None)

    # Static build, reloaded when a nightly build rewrites meta.json. Loading the timetable and
    # the planner takes seconds, so a new build loads in a background thread while the old one
    # keeps serving; only the very first load (nothing to serve yet) waits for it.
    state: dict = {"static": None, "static_mtime": None, "planner": None, "derived": lineview.Derived()}
    meta_path = DATA_DIR / "static" / "meta.json"
    loading = threading.Lock()

    def load_static(mtime: float) -> None:
        try:
            static = Static.load(DATA_DIR)
            # Load the timetable now, not inside a poll.
            p = Planner(DATA_DIR / "static") if static is not None and static.timetable is not None else None
            state["static"], state["planner"], state["static_mtime"] = static, p, mtime
            logging.getLogger(__name__).info("loaded static build %s", static.meta.get("feedVersion") if static else None)
        except Exception:
            logging.getLogger(__name__).exception("failed to load static build")
        finally:
            loading.release()

    def current_static() -> Static | None:
        try:
            mtime = meta_path.stat().st_mtime
        except FileNotFoundError:
            return state["static"]
        if mtime != state["static_mtime"] and loading.acquire(blocking=False):
            if state["static"] is None:
                load_static(mtime)
            else:
                threading.Thread(target=load_static, args=(mtime,), daemon=True).start()
        return state["static"]

    history = History(DATA_DIR / "logs")
    reliability = Reliability(DATA_DIR / "history")
    speeds = Speeds(DATA_DIR)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await asyncio.to_thread(current_static)  # the first load, before polls need it
        try:
            await asyncio.to_thread(speeds.seed, datetime.now(timezone.utc))
        except Exception:
            logging.getLogger(__name__).exception("failed to seed the live speeds")
        tasks = [asyncio.create_task(poller.run()), asyncio.create_task(nightly.run_forever(DATA_DIR))] if start_polling else []
        regional = os.environ.get("MHD_NO_REGIONAL") != "1"
        if start_polling and regional:
            tasks.append(asyncio.create_task(idsbk.Sweeper(poller.logger, poller.apply_regional).run()))
        # Only production reports to the monitor: a dev server's heartbeats would hide an outage.
        if start_polling and os.environ.get("RAILWAY_ENVIRONMENT_NAME") == "production":
            tasks.append(asyncio.create_task(heartbeat.run_forever(poller, regional)))
        yield
        for task in tasks:
            task.cancel()

    app = FastAPI(title="MHD naživo", lifespan=lifespan)
    app.state.poller = poller
    # The latest poll's trip matching (realtime.Realtime): trip_delays(), trip_vehicle(), …
    app.state.realtime = state["derived"].realtime

    stop_events = StopEventTracker()

    def on_update(snap) -> None:
        t0 = time.perf_counter()
        state["derived"] = lineview.derive_poll(snap, current_static())
        app.state.realtime = state["derived"].realtime
        events = stop_events.update(state["derived"].realtime)
        speeds.add(events)
        if poller.logger is not None and snap.updated_at is not None:
            poller.logger.log_stop_events(snap.updated_at, events)
        ms = (time.perf_counter() - t0) * 1000
        if ms > 500:
            logging.getLogger(__name__).warning("deriving the poll took %d ms", ms)

    poller.on_update = on_update
    if poller.snapshot.polled_at is not None:
        on_update(poller.snapshot)
    app.add_middleware(GZipMiddleware, minimum_size=1000)

    auth = os.environ.get("MHD_BASIC_AUTH")
    if auth:
        expected = "Basic " + base64.b64encode(auth.encode()).decode()

        @app.middleware("http")
        async def basic_auth(request: Request, call_next):
            got = request.headers.get("authorization", "")
            if not secrets.compare_digest(got.encode(), expected.encode()):
                return Response(
                    status_code=401, headers={"WWW-Authenticate": 'Basic realm="MHD nazivo"'}
                )
            return await call_next(request)

    no_store = {"Cache-Control": "no-store"}

    @app.get("/api/live")
    def live():
        snap = poller.snapshot
        derived = state["derived"]
        now = datetime.now(timezone.utc)
        vehicles = []
        for v in snap.vehicles:
            vehicles.append(_vehicle(v, snap, derived, now))
        body = {"feed": derive.feed_status(snap, now), "regionalFeed": derive.feed_status(snap.regional, now), "vehicles": vehicles}
        return JSONResponse(body, headers=no_store)

    @app.get("/api/station/{code}")
    def station(code: str, stop: str | None = None):
        static = current_static()
        if static is None:
            return JSONResponse({"error": "static data not built"}, status_code=503)
        st = static.stations.get(code)
        if st is None:
            return JSONResponse({"error": f"unknown station {code}"}, status_code=404)
        if stop is not None and stop not in st["stops"]:
            return JSONResponse({"error": f"stop {stop} is not a platform of station {code}"}, status_code=404)
        now = datetime.now(timezone.utc)
        rt = state["derived"].realtime
        platforms = [
            {
                "stopId": sid,
                "platform": static.stops[sid].get("platform"),
                "lat": static.stops[sid]["lat"],
                "lon": static.stops[sid]["lon"],
                "lines": static.stops[sid].get("lines", []),
            }
            for sid in st["stops"]
            if sid in static.stops
        ]
        body = {
            "code": code,
            "name": st["name"],
            "lat": st["lat"],
            "lon": st["lon"],
            "lines": st.get("lines", []),
            "platforms": platforms,
            "departures": rt.departures([stop] if stop else st["stops"], now),
            "feed": derive.feed_status(poller.snapshot, now),
        }
        return JSONResponse(body, headers=no_store)

    @app.get("/api/vehicle/{key}")
    def vehicle(key: str):
        snap = poller.snapshot
        v = next((v for v in snap.vehicles if v.key == key), None)
        if v is None:
            return JSONResponse({"error": f"unknown vehicle {key}"}, status_code=404)
        now = datetime.now(timezone.utc)
        derived = state["derived"]
        body = {
            "vehicle": _vehicle(v, snap, derived, now),
            "trip": derived.realtime.vehicle_trip(key, now, stop_events.passed_at(derived.realtime, key)),
            "feed": derive.feed_status(snap, now),
        }
        return JSONResponse(body, headers=no_store)

    def current_planner() -> Planner | None:
        return state["planner"] if current_static() is not None else None

    def _place(value: str, name: str | None) -> dict:
        """\"93\" is a station code, \"48.15,17.11\" a map point or the user's location."""
        if "," in value:
            lat, lon = (float(x) for x in value.split(",", 1))
            return {"lat": lat, "lon": lon, "name": name or "Zvolené miesto"}
        return {"station": value}

    @app.get("/api/plan")
    def plan(
        origin: str = Query(alias="from"),
        dest: str = Query(alias="to"),
        at: str | None = None,
        fromName: str | None = None,
        toName: str | None = None,
        track: str | None = None,
    ):
        """track: the open option's rides as "trip~from stop~to stop" joined by commas. While
        departing now, it stays in the options (first) after it has left or lost a connection."""
        p = current_planner()
        if p is None:
            return JSONResponse({"error": "static data not built"}, status_code=503)
        now = datetime.now(timezone.utc)
        try:
            depart = datetime.fromisoformat(at) if at else now
            if depart.tzinfo is None:  # a wall-clock time in Bratislava
                depart = depart.replace(tzinfo=TZ)
            o, d = _place(origin, fromName), _place(dest, toName)
        except ValueError:
            return JSONResponse({"error": "bad from, to or at"}, status_code=400)
        rt = state["derived"].realtime
        # Current delays only matter for trips leaving around now.
        live = timedelta(minutes=-30) < depart - now < timedelta(hours=2)
        try:
            options, reason = p.plan_with_reason(o, d, depart, delays=rt.trip_delays() if live else None)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=404)
        if live and track:
            try:
                sig = [tuple(r.split("~")) for r in track.split(",")]
                if len(sig) > MAX_RIDES or any(len(r) != 3 for r in sig):
                    raise ValueError
            except ValueError:
                return JSONResponse({"error": "bad track"}, status_code=400)
            known = {tuple((leg["trip"], leg["from"]["stop"], leg["to"]["stop"]) for leg in it["legs"]
                           if leg["kind"] == "ride") for it in options}
            if tuple(sig) not in known:
                tracked = p.track(o, d, sig, now, delays=rt.trip_delays())
                if tracked is not None:
                    options.insert(0, {**tracked, "tracked": True})
                    reason = None
        vehicles = rt.trip_vehicle() if live else {}
        nexts = rt.trip_next_stop() if live else {}
        for it in options:
            for leg in it["legs"]:
                if leg["kind"] == "ride":
                    leg["vehicle"] = vehicles.get(leg["trip"])
                    # The vehicle's way to the boarding stop, for the map.
                    k = nexts.get(leg["trip"]) if leg["vehicle"] else None
                    leg["approach"] = None if k is None else p.approach(leg["trip"], leg["from"]["stop"], k)
        return JSONResponse({"options": options, "reason": reason, "live": live}, headers=no_store)

    @app.get("/api/reach")
    def reach(origin: str = Query(alias="from"), at: str | None = None, limit: int = Query(30, alias="min", ge=5, le=60)):
        """Where public transport and walking get to within `min` minutes: the stops reached with
        their arrival times; the client walks on from them at the pace in "walk"."""
        p = current_planner()
        if p is None:
            return JSONResponse({"error": "static data not built"}, status_code=503)
        now = datetime.now(timezone.utc)
        try:
            depart = datetime.fromisoformat(at) if at else now
            if depart.tzinfo is None:  # a wall-clock time in Bratislava
                depart = depart.replace(tzinfo=TZ)
            o = _place(origin, None)
        except ValueError:
            return JSONResponse({"error": "bad from or at"}, status_code=400)
        live = timedelta(minutes=-30) < depart - now < timedelta(hours=2)
        delays = state["derived"].realtime.trip_delays() if live else None
        try:
            res = p.reach(o, depart, limit * 60, delays=delays)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=404)
        body = {**res, "depart": depart.astimezone(TZ).isoformat(timespec="seconds"), "limit": limit * 60,
                "live": live, "walk": {"speed": WALK_SPEED, "detour": DETOUR, "maxM": WALK_ONLY_M}}
        return JSONResponse(body, headers=no_store)

    @app.get("/api/line/{line}")
    def line(line: str):
        static = current_static()
        if static is None:
            return JSONResponse({"error": "static data not built"}, status_code=503)
        now = datetime.now(timezone.utc)
        snap = poller.snapshot
        view = lineview.line_view(line, snap, state["derived"], static, now)
        if view is None:
            return JSONResponse({"error": f"unknown line {line}"}, status_code=404)
        view["feed"] = derive.feed_status(snap, now)
        return JSONResponse(view, headers=no_store)

    @app.get("/api/line/{line}/reliability")
    def line_reliability(line: str, days: str = "workdays"):
        """Delays by stop and hour over the last weeks (reliability.py); days: workdays or weekends."""
        static = current_static()
        if static is None:
            return JSONResponse({"error": "static data not built"}, status_code=503)
        if days not in KINDS:
            return JSONResponse({"error": f"days must be one of {', '.join(KINDS)}"}, status_code=400)
        body = reliability.get(static, line, days)
        if body is None:
            return JSONResponse({"error": f"unknown line {line}"}, status_code=404)
        # It only changes when the nightly retention keeps another day.
        return JSONResponse(body, headers={"Cache-Control": "max-age=600"})

    @app.get("/api/status")
    def status():
        now = datetime.now(timezone.utc)
        snap = poller.snapshot
        body = lineview.city_status(snap, state["derived"], current_static(), now)
        body["feed"] = derive.feed_status(snap, now)
        try:
            body["history"] = history.status(now)
        except Exception:
            logging.getLogger(__name__).exception("history failed")
            body["history"] = None
        return JSONResponse(body, headers=no_store)

    @app.get("/api/replay")
    def replay_range():
        return JSONResponse(replay.available(DATA_DIR / "logs"), headers=no_store)

    # Requests waiting for a slot hold no worker thread, so scrubbing never starves /api/live.
    replay_slots = asyncio.Semaphore(replay.MAX_READERS)

    @app.get("/api/replay/{t}")
    async def replay_chunk(t: int):
        """The logged positions of the 10-minute chunk holding Unix time t (replay.py)."""
        if t < 0:
            return JSONResponse({"error": "bad time"}, status_code=400)
        async with replay_slots:
            body = await asyncio.to_thread(replay.chunk, DATA_DIR / "logs", t)
        # A finished chunk never changes; the browser keeps it while the user scrubs back and forth.
        cache = "private, max-age=86400" if body["complete"] else "no-store"
        return JSONResponse(body, headers={"Cache-Control": cache})

    @app.get("/api/speeds")
    def speed_view(view: str = "live", at: str | None = None):
        """How fast trips ran each hop between stops against the timetable: in the last half
        hour (live), or typically on this kind of day around `at` (HH:MM; default now)."""
        now = datetime.now(timezone.utc)
        if view == "live":
            return JSONResponse(speeds.live(now), headers=no_store)
        if view != "typical":
            return JSONResponse({"error": "view is live or typical"}, status_code=400)
        secs = None
        if at:
            try:
                h, m = (int(x) for x in at.split(":"))
                if not (0 <= h < 24 and 0 <= m < 60):
                    raise ValueError
            except ValueError:
                return JSONResponse({"error": "bad at"}, status_code=400)
            secs = h * 3600 + m * 60
        return JSONResponse(speeds.typical(now, secs), headers=no_store)

    @app.get("/api/speeds/geometry")
    def speed_geometry():
        """Every hop's line on the map, its length and the lines that run it."""
        p = current_planner()
        if p is None:
            return JSONResponse({"error": "static data not built"}, status_code=503)
        # Not cached by the browser: a new static build or deploy can change it at any time. The
        # server keeps it in memory, and the client loads it once per page.
        return JSONResponse(speeds.geometry(p), headers={"Cache-Control": "no-cache"})

    static_dir = DATA_DIR / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/api/static", StaticFiles(directory=static_dir), name="static-data")

    if FRONTEND_DIR.exists():
        # Hashed build assets are immutable; every other path is the single-page app, so deep
        # links such as /linka/83 or /vozidlo/1843 load index.html.
        app.mount("/assets", StaticFiles(directory=FRONTEND_DIR / "assets"), name="assets")
        root = FRONTEND_DIR.resolve()

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            f = (root / path).resolve()
            if path and f.is_file() and f.is_relative_to(root):
                headers = {"Cache-Control": "no-cache"} if f.name in ("sw.js", "manifest.webmanifest") else None
                return FileResponse(f, headers=headers)
            if path.startswith("api/"):
                return JSONResponse({"error": "not found"}, status_code=404)
            return FileResponse(root / "index.html", headers={"Cache-Control": "no-cache"})

    return app


def _vehicle(v, snap, derived: lineview.Derived, now: datetime) -> dict:
    service = derived.service(v.key)
    j = derive.vehicle_json(v, snap, now, service)
    m = derived.matches.get(v.key)
    j["dir"] = m.direction if m else None
    j["service"] = service
    j["trip"] = derived.realtime.trip_id(v.key)
    return j


app = create_app()
