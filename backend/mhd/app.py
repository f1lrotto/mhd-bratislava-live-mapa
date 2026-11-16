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

from . import derive
from .logger import PollLogger
from .poller import Poller

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("MHD_DATA_DIR", ROOT / "data"))
FRONTEND_DIR = ROOT / "frontend" / "dist"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def create_app(poller: Poller | None = None, start_polling: bool | None = None) -> FastAPI:
    if start_polling is None:
        start_polling = os.environ.get("MHD_NO_POLL") != "1"
    if poller is None:
        poller = Poller(PollLogger(DATA_DIR / "logs") if start_polling else None)

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

    @app.get("/api/live")
    def live():
        snap = poller.snapshot
        now = datetime.now(timezone.utc)
        return JSONResponse(
            {
                "feed": derive.feed_status(snap, now),
                "vehicles": [derive.vehicle_json(v, snap, now) for v in snap.vehicles],
            },
            headers={"Cache-Control": "no-store"},
        )

    if FRONTEND_DIR.exists():
        app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")

    return app


app = create_app()
