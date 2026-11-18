"""User accounts: the Better Auth server (auth/server.js) runs as a Node child process of this one,
on 127.0.0.1, and /api/auth/* is forwarded to it. One Railway service and one volume hold both:
its SQLite database is <data>/accounts/auth.db.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import time
from pathlib import Path

import httpx
from fastapi import Request
from fastapi.responses import JSONResponse, Response

log = logging.getLogger(__name__)

AUTH_DIR = Path(__file__).resolve().parents[2] / "auth"
PORT = int(os.environ.get("AUTH_PORT", "8790"))

# What Better Auth needs from the browser's request: the session cookie, the body's type and the
# origin it checks against CSRF. The visitor's address only feeds its in-memory rate limits.
REQUEST_HEADERS = ("cookie", "content-type", "accept", "origin", "referer", "sec-fetch-site", "sec-fetch-mode")
RESPONSE_HEADERS = ("content-type", "cache-control", "location")
# Every account request is a small JSON body; anything bigger is refused before it is buffered,
# so a large upload can't run the one replica out of memory.
MAX_BODY = 64 * 1024


class TooLarge(Exception):
    pass


async def _body(request: Request) -> bytes:
    if int(request.headers.get("content-length") or 0) > MAX_BODY:
        raise TooLarge
    chunks, size = [], 0
    async for chunk in request.stream():  # also caps chunked bodies, which have no length
        size += len(chunk)
        if size > MAX_BODY:
            raise TooLarge
        chunks.append(chunk)
    return b"".join(chunks)


class _RedactTokens(logging.Filter):
    """Uvicorn's access log: no lines for /api/auth (email-link tokens in paths), no ?token=
    elsewhere, and no visitor addresses (the privacy page says the app doesn't log them)."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str):
            path = args[2]
            if path.startswith("/api/auth/"):
                return False
            record.args = ("-", args[1], re.sub(r"token=[^&]*", "token=…", path), *args[3:])
        return True


def quiet_logs() -> None:
    """Keep email-link tokens out of the logs. httpx logs every URL it requests at INFO: its lines
    for the accounts server are dropped (the feed's requests still log)."""
    local = f"127.0.0.1:{PORT}"
    logging.getLogger("httpx").addFilter(lambda r: local not in r.getMessage())
    logging.getLogger("uvicorn.access").addFilter(_RedactTokens())


def available() -> bool:
    return (AUTH_DIR / "node_modules").is_dir() and shutil.which("node") is not None


async def run_forever(data_dir: Path) -> None:
    """Run the accounts server, restarting it when it exits."""
    env = {**os.environ, "MHD_DATA_DIR": str(data_dir), "AUTH_PORT": str(PORT), "NODE_ENV": "production"}
    backoff = 1.0
    while True:
        started = time.monotonic()
        proc = await asyncio.create_subprocess_exec("node", "server.js", cwd=AUTH_DIR, env=env)
        try:
            code = await proc.wait()
        except asyncio.CancelledError:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), 5)
            except TimeoutError:
                proc.kill()
            raise
        if time.monotonic() - started > 60:  # it ran fine for a while: restart at once
            backoff = 1.0
        log.error("accounts server exited with %s, restarting in %.0f s", code, backoff)
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, 60)


class Proxy:
    def __init__(self) -> None:
        self.client = httpx.AsyncClient(base_url=f"http://127.0.0.1:{PORT}", timeout=15)

    async def __call__(self, path: str, request: Request) -> Response:
        headers = {k: v for k in REQUEST_HEADERS if (v := request.headers.get(k)) is not None}
        # The address the visitor opened (uvicorn's --proxy-headers already applied Railway's),
        # so cookies and the trusted origin are for that host.
        headers["x-forwarded-host"] = request.headers.get("host", "")
        headers["x-forwarded-proto"] = request.url.scheme
        # For rate limits: Railway's edge sets X-Real-IP to the visitor's address.
        ip = request.headers.get("x-real-ip") or (request.client.host if request.client else None)
        if ip:
            headers["x-forwarded-for"] = ip
        try:
            body = await _body(request)
        except TooLarge:
            return JSONResponse({"message": "request too large"}, status_code=413)
        try:
            r = await self.client.request(
                request.method,
                f"/api/auth/{path}",
                params=request.query_params,
                content=body,
                headers=headers,
            )
        except httpx.TransportError:
            return JSONResponse({"message": "accounts unavailable"}, status_code=503)
        resp = Response(content=r.content, status_code=r.status_code)
        for k in RESPONSE_HEADERS:
            if k in r.headers:
                resp.headers[k] = r.headers[k]
        for cookie in r.headers.get_list("set-cookie"):
            resp.headers.append("set-cookie", cookie)
        resp.headers.setdefault("cache-control", "no-store")
        return resp
