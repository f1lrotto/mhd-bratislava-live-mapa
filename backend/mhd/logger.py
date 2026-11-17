"""Append-only Parquet log of every poll.

Each poll is written immediately as a small part file, so a crash loses nothing. When the hour
rolls over (and on startup), the part files of finished hours are compacted into one file per hour:

    <root>/vehicles/date=2026-11-16/hour=16.parquet   one row per vehicle per poll
    <root>/polls/date=2026-11-16/hour=16.parquet      one row per poll attempt, including failures
    <root>/stop_events/date=2026-11-16/hour=16.parquet   one row per trip per stop passed (stopevents)

Partitions use UTC. The logger deletes nothing but part files after a successful compaction; old
days are removed by the nightly retention job (retention.py).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from .feed import Vehicle

log = logging.getLogger(__name__)

VEHICLE_SCHEMA = pa.schema(
    [
        ("ts", pa.timestamp("ms", tz="UTC")),
        ("key", pa.string()),
        ("line", pa.string()),
        ("dest", pa.string()),
        ("type", pa.string()),
        ("lat", pa.float64()),
        ("lon", pa.float64()),
        ("delay_s", pa.int32()),
        ("state", pa.int8()),
        ("azimuth", pa.int16()),
    ]
)

POLL_SCHEMA = pa.schema(
    [
        ("ts", pa.timestamp("ms", tz="UTC")),
        ("ok", pa.bool_()),
        ("vehicles", pa.int32()),
        ("duration_ms", pa.int32()),
        ("error", pa.string()),
    ]
)


STOP_EVENT_SCHEMA = pa.schema(
    [
        ("ts", pa.timestamp("ms", tz="UTC")),  # the poll that recorded it
        ("service_date", pa.date32()),
        ("trip", pa.string()),
        ("line", pa.string()),
        ("dir", pa.string()),
        ("seq", pa.int16()),  # the stop's index in the trip
        ("stop", pa.string()),
        ("scheduled", pa.timestamp("s", tz="UTC")),
        ("actual", pa.timestamp("s", tz="UTC")),
        ("delay_s", pa.int32()),
        ("vehicle", pa.string()),
        ("final", pa.bool_()),  # the trip's last stop: `actual` is its arrival, not its departure
    ]
)

DATASETS = ("vehicles", "polls", "stop_events")


def _hour_dir(root: Path, dataset: str, ts: datetime) -> tuple[Path, str]:
    ts = ts.astimezone(timezone.utc)
    return root / dataset / f"date={ts:%Y-%m-%d}", f"hour={ts:%H}"


def _fsync_dir(d: Path) -> None:
    fd = os.open(d, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _atomic_write(table: pa.Table, target: Path, **kw) -> None:
    tmp = target.with_name(f".{target.name}.tmp")
    pq.write_table(table, tmp, **kw)
    with open(tmp, "rb") as f:
        os.fsync(f.fileno())
    os.replace(tmp, target)


class PollLogger:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._current_hour: tuple[Path, str] | None = None
        self.compact_finished()

    def _write_part(self, dataset: str, table: pa.Table, ts: datetime) -> None:
        d, hour = _hour_dir(self.root, dataset, ts)
        d.mkdir(parents=True, exist_ok=True)
        name = f"{hour}.part-{int(ts.timestamp() * 1000)}.parquet"
        _atomic_write(table, d / name)

    def log_poll(
        self,
        ts: datetime,
        vehicles: list[Vehicle] | None,
        duration_ms: int,
        error: str | None,
    ) -> None:
        # The poll row is written on its own so a bad vehicle table never hides the poll.
        if vehicles:
            try:
                n = len(vehicles)
                table = pa.table(
                    {
                        "ts": [ts] * n,
                        "key": [v.key for v in vehicles],
                        "line": [v.line for v in vehicles],
                        "dest": [v.dest for v in vehicles],
                        "type": [v.type for v in vehicles],
                        "lat": [v.lat for v in vehicles],
                        "lon": [v.lon for v in vehicles],
                        "delay_s": [v.delay_s for v in vehicles],
                        "state": [v.state for v in vehicles],
                        "azimuth": [v.azimuth for v in vehicles],
                    },
                    schema=VEHICLE_SCHEMA,
                )
                self._write_part("vehicles", table, ts)
            except Exception:  # logging must never stop the poller
                log.exception("failed to write vehicle log")
                error = error or "vehicle log write failed"
        try:
            poll = pa.table(
                {
                    "ts": [ts],
                    "ok": [error is None],
                    "vehicles": [len(vehicles) if vehicles else 0],
                    "duration_ms": [duration_ms],
                    "error": [error],
                },
                schema=POLL_SCHEMA,
            )
            self._write_part("polls", poll, ts)
        except Exception:
            log.exception("failed to write poll log")
            return

        hour = _hour_dir(self.root, "polls", ts)
        if self._current_hour is not None and hour != self._current_hour:
            self.compact_finished(now=ts)
        self._current_hour = hour

    def log_stop_events(self, ts: datetime, rows: list[dict]) -> None:
        if not rows:
            return
        try:
            self._write_part("stop_events", pa.Table.from_pylist(rows, schema=STOP_EVENT_SCHEMA), ts)
        except Exception:  # logging must never stop the poller
            log.exception("failed to write stop events")

    def recent(self, since: datetime, now: datetime | None = None) -> list[tuple[datetime, list[Vehicle]]]:
        """Logged vehicle polls from `since` until now, oldest first, for restoring state on restart."""
        now = now or datetime.now(timezone.utc)
        files: list[Path] = []
        h = since.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
        while h <= now:
            d, hour = _hour_dir(self.root, "vehicles", h)
            files += sorted(d.glob(f"{hour}.parquet")) + sorted(d.glob(f"{hour}.part-*.parquet"))
            h += timedelta(hours=1)
        polls: dict[datetime, list[Vehicle]] = {}
        for f in files:
            try:
                rows = pq.read_table(f).to_pylist()
            except Exception:
                log.exception("unreadable log file %s", f)
                continue
            for r in rows:
                if r["ts"] < since:
                    continue
                polls.setdefault(r["ts"], []).append(
                    Vehicle(r["key"], r["line"], r["dest"], r["type"], r["lat"], r["lon"], r["delay_s"], r["state"], r["azimuth"])
                )
        return sorted(polls.items())

    def compact_finished(self, now: datetime | None = None) -> None:
        """Merge part files of every hour before the current one into <hour>.parquet."""
        now = now or datetime.now(timezone.utc)
        for dataset in DATASETS:
            cur_dir, cur_hour = _hour_dir(self.root, dataset, now)
            base = self.root / dataset
            if not base.exists():
                continue
            groups: dict[tuple[Path, str], list[Path]] = {}
            for part in base.glob("date=*/hour=*.part-*.parquet"):
                hour = part.name.split(".part-")[0]
                if part.parent == cur_dir and hour == cur_hour:
                    continue
                groups.setdefault((part.parent, hour), []).append(part)
            for (d, hour), parts in groups.items():
                try:
                    self._compact(d, hour, sorted(parts))
                except Exception:
                    log.exception("failed to compact %s/%s", d, hour)

    @staticmethod
    def _compact(d: Path, hour: str, parts: list[Path]) -> None:
        target = d / f"{hour}.parquet"
        tables = [pq.read_table(p) for p in parts]
        if target.exists():
            # Parts left over from a crash between replace and unlink are already in the target;
            # each part holds one poll, so skip parts whose ts the target already has.
            old = pq.read_table(target)
            seen = set(old.column("ts").to_pylist())
            tables = [old] + [t for t in tables if t.num_rows and t.column("ts")[0].as_py() not in seen]
        merged = pa.concat_tables(tables).sort_by("ts")
        _atomic_write(merged, target, compression="zstd")
        _fsync_dir(d)  # the new hour file must be durable before its parts go
        for p in parts:
            p.unlink(missing_ok=True)
