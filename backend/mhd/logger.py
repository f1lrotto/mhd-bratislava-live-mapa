"""Append-only Parquet log of every poll.

Each poll is written immediately as a small part file, so a crash loses nothing. When the hour
rolls over (and on startup), the part files of finished hours are compacted into one file per hour:

    <root>/vehicles/date=2026-11-16/hour=16.parquet   one row per vehicle per poll
    <root>/polls/date=2026-11-16/hour=16.parquet      one row per poll attempt, including failures

Partitions use UTC. Nothing is ever deleted except part files after a successful compaction.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
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


def _hour_dir(root: Path, dataset: str, ts: datetime) -> tuple[Path, str]:
    ts = ts.astimezone(timezone.utc)
    return root / dataset / f"date={ts:%Y-%m-%d}", f"hour={ts:%H}"


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
        tmp = d / f".{name}.tmp"
        pq.write_table(table, tmp)
        os.replace(tmp, d / name)

    def log_poll(
        self,
        ts: datetime,
        vehicles: list[Vehicle] | None,
        duration_ms: int,
        error: str | None,
    ) -> None:
        try:
            if vehicles:
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
        except Exception:  # logging must never stop the poller
            log.exception("failed to write poll log")
            return

        hour = _hour_dir(self.root, "polls", ts)
        if self._current_hour is not None and hour != self._current_hour:
            self.compact_finished(now=ts)
        self._current_hour = hour

    def compact_finished(self, now: datetime | None = None) -> None:
        """Merge part files of every hour before the current one into <hour>.parquet."""
        now = now or datetime.now(timezone.utc)
        for dataset in ("vehicles", "polls"):
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
        if target.exists():  # a part written after an earlier compaction (e.g. clock skew)
            tables.insert(0, pq.read_table(target))
        merged = pa.concat_tables(tables).sort_by("ts")
        tmp = d / f".{hour}.compact.tmp"
        pq.write_table(merged, tmp, compression="zstd")
        os.replace(tmp, target)
        for p in parts:
            p.unlink(missing_ok=True)
