"""Nightly jobs, run by the server itself at NIGHTLY_AT local time: the static build (a no-op
unless DPB or IDS BK published a new GTFS), then retention.

The build also runs at startup. It is a no-op there too unless a feed changed, so a deploy that
adds a feed (or one published while the server was down) is built without waiting for the night.
On a fresh data volume it runs again every FIRST_BUILD_RETRY_S until it succeeds.

They run in the server, not as a separate cron service, because the data volume can only be
mounted by one service. Each job is a subprocess, so its memory is returned when it ends.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

from .static import TZ

log = logging.getLogger(__name__)

NIGHTLY_AT = time(3, 30)  # after the last night trips, before the first morning ones
FIRST_BUILD_RETRY_S = 600
BACKEND = Path(__file__).resolve().parents[1]


def seconds_until_next(now: datetime) -> float:
    local = now.astimezone(TZ)
    at = datetime.combine(local.date(), NIGHTLY_AT, TZ)
    if at <= local:
        at = datetime.combine(local.date() + timedelta(days=1), NIGHTLY_AT, TZ)
    return (at - now).total_seconds()


async def _job(module: str, data_dir: Path) -> None:
    try:
        p = await asyncio.create_subprocess_exec(sys.executable, "-m", module, "--data-dir", str(data_dir), cwd=BACKEND)
        try:
            code = await p.wait()
        except asyncio.CancelledError:  # the server is stopping; don't leave the job behind
            p.kill()
            raise
        (log.info if code == 0 else log.error)("%s exited with %d", module, code)
    except Exception:
        log.exception("%s failed to start", module)


async def run_forever(data_dir: Path) -> None:
    await _job("mhd.build", data_dir)
    while not (data_dir / "static" / "meta.json").exists():
        await asyncio.sleep(FIRST_BUILD_RETRY_S)
        await _job("mhd.build", data_dir)
    while True:
        await asyncio.sleep(seconds_until_next(datetime.now(timezone.utc)))
        await _job("mhd.build", data_dir)
        await _job("mhd.retention", data_dir)
