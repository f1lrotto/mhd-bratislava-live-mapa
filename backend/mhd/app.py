"""HTTP API and static file server.

Environment:
  MHD_DATA_DIR      where logs and the static build live (default: ../data next to backend/)
  MHD_NO_POLL=1     don't start the poller (tests, frontend work against a fixture)
  MHD_BASIC_AUTH    "user:password" to put everything behind HTTP basic auth while v1 is private

Run a single worker (no `--workers N`): the poller and logger live in the process, and DPB
must see one client.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import derive, lineview
from .history import History
from .logger import PollLogger
from .poller import Poller
from .static import Static

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("MHD_DATA_DIR", ROOT / "data"))
FRONTEND_DIR = ROOT / "frontend" / "dist"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def create_app(poller: Poller | None = None, start_polling: bool | None = None) -> FastAPI:
    if start_polling is None:
        start_polling = os.environ.get("MHD_NO_POLL") != "1"
    if poller is None:
        poller = Poller(PollLogger(DATA_DIR / "logs") if start_polling else None)

    # Static build, reloaded when a nightly build rewrites meta.json.
    state: dict = {"static": None, "static_mtime": None, "derived": lineview.Derived()}
    meta_path = DATA_DIR / "static" / "meta.json"

    def current_static() -> Static | None:
        try:
            mtime = meta_path.stat().st_mtime
        except FileNotFoundError:
            return state["static"]
        if mtime != state["static_mtime"]:
            try:
                state["static"] = Static.load(DATA_DIR)
                state["static_mtime"] = mtime
                logging.getLogger(__name__).info("loaded static build %s", state["static"].meta.get("feedVersion"))
            except Exception:
                logging.getLogger(__name__).exception("failed to load static build")
        return state["static"]

    def on_update(snap) -> None:
        state["derived"] = lineview.derive_poll(snap, current_static())

    poller.on_update = on_update
    if poller.snapshot.polled_at is not None:
        on_update(poller.snapshot)
    history = History(DATA_DIR / "logs")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = asyncio.create_task(poller.run()) if start_polling else None
        yield
        if task:
            task.cancel()

    app = FastAPI(title="MHD naživo", lifespan=lifespan)
    app.state.poller = poller
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
            j = derive.vehicle_json(v, snap, now)
            m = derived.matches.get(v.key)
            j["dir"] = m.direction if m else None
            vehicles.append(j)
        return JSONResponse({"feed": derive.feed_status(snap, now), "vehicles": vehicles}, headers=no_store)

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

    @app.get("/api/status")
    def status():
        now = datetime.now(timezone.utc)
        snap = poller.snapshot
        body = lineview.city_status(snap, current_static(), now)
        body["feed"] = derive.feed_status(snap, now)
        try:
            body["history"] = history.status(now)
        except Exception:
            logging.getLogger(__name__).exception("history failed")
            body["history"] = None
        return JSONResponse(body, headers=no_store)

    static_dir = DATA_DIR / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/api/static", StaticFiles(directory=static_dir), name="static-data")

    if FRONTEND_DIR.exists():
        app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")

    return app


app = create_app()
