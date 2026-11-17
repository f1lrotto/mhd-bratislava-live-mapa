"""Nightly retention: keep what's worth keeping forever, delete raw logs after RAW_DAYS.

For each finished service day it writes

    <data>/history/stop_events/2026-11-16.parquet   every stop every trip passed, one row each
    <data>/history/delays/2026-11-16.parquet        per line, direction and 10-minute bucket of
                                                    scheduled time: count, mean/median/p90/max
                                                    delay, number 5+ min late

and then deletes the raw 15-second logs (vehicles, polls, stop_events) older than RAW_DAYS. Raw
stop events of a UTC date are only deleted once every service day they can belong to is written.
Safe to run any number of times: written days are skipped.

    uv run python -m mhd.retention [--data-dir DIR]
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from .derive import LATE_S
from .logger import DATASETS, STOP_EVENT_SCHEMA, _atomic_write
from .static import TZ, day_start

log = logging.getLogger(__name__)

RAW_DAYS = 30  # the late-share baseline (history.py) looks back four weeks
SETTLE_DAYS = 2  # a service day's night trips end the next morning; wait until it's surely over
BUCKET_S = 600


def _raw_dates(logs: Path, dataset: str) -> list[date]:
    base = logs / dataset
    if not base.exists():
        return []
    return sorted(date.fromisoformat(d.name[5:]) for d in base.glob("date=*") if d.is_dir())


def _read_raw_events(logs: Path, day: date) -> pa.Table:
    # Service day D runs from about 22:00 UTC on D-1 (local midnight) to about 04:00 UTC on D+1.
    tables = []
    for d in (day - timedelta(days=1), day, day + timedelta(days=1)):
        for f in sorted((logs / "stop_events" / f"date={d}").glob("hour=*.parquet")):
            try:
                tables.append(pq.read_table(f, schema=STOP_EVENT_SCHEMA))
            except Exception:
                log.exception("unreadable log file %s", f)
    if not tables:
        return STOP_EVENT_SCHEMA.empty_table()
    t = pa.concat_tables(tables)
    return t.filter(pc.equal(t["service_date"], pa.scalar(day, pa.date32())))


def stop_events(logs: Path, day: date) -> pa.Table:
    """The day's stop events, one per trip and stop (the first recorded if two vehicles ran it)."""
    t = _read_raw_events(logs, day).sort_by("ts")
    if t.num_rows:
        t = t.append_column("_i", pa.array(range(t.num_rows), pa.int64()))
        first = t.group_by(["trip", "seq"]).aggregate([("_i", "min")])["_i_min"]
        t = t.take(first).drop_columns("_i")
    return t.sort_by([("line", "ascending"), ("dir", "ascending"), ("scheduled", "ascending"), ("seq", "ascending")])


def delays(events: pa.Table, day: date) -> pa.Table:
    """Delay per line, direction and 10-minute bucket of scheduled time (bucket 0 starts at the
    service day's midnight; night trips after midnight have buckets of 144 and up)."""
    start = pa.scalar(day_start(day).astimezone(timezone.utc), pa.timestamp("s", tz="UTC"))
    secs = pc.cast(pc.subtract(events["scheduled"], start), pa.int64())
    bucket = pc.cast(pc.floor(pc.divide(pc.cast(secs, pa.float64()), BUCKET_S)), pa.int16())
    t = pa.table(
        {
            "line": events["line"],
            "dir": events["dir"],
            "bucket": bucket,
            "delay_s": events["delay_s"],
            "late": pc.cast(pc.greater_equal(events["delay_s"], LATE_S), pa.int32()),
        }
    )
    g = t.group_by(["line", "dir", "bucket"]).aggregate(
        [
            ("delay_s", "count"),
            ("delay_s", "mean"),
            ("delay_s", "approximate_median"),
            ("delay_s", "tdigest", pc.TDigestOptions(q=0.9)),
            ("delay_s", "max"),
            ("late", "sum"),
        ]
    )
    out = pa.table(
        {
            "service_date": pa.array([day] * g.num_rows, pa.date32()),
            "line": g["line"],
            "dir": g["dir"],
            "bucket": g["bucket"],
            "events": pc.cast(g["delay_s_count"], pa.int32()),
            "delay_mean": pc.round(g["delay_s_mean"], 1),
            "delay_p50": pc.cast(pc.round(g["delay_s_approximate_median"]), pa.int32()),
            "delay_p90": pc.cast(pc.round(pc.list_element(g["delay_s_tdigest"], 0)), pa.int32()),
            "delay_max": g["delay_s_max"],
            "late": pc.cast(g["late_sum"], pa.int32()),
        }
    )
    return out.sort_by([("line", "ascending"), ("dir", "ascending"), ("bucket", "ascending")])


def run(data: Path, now: datetime | None = None) -> None:
    now = now or datetime.now(timezone.utc)
    logs, hist = data / "logs", data / "history"
    last_settled = now.astimezone(TZ).date() - timedelta(days=SETTLE_DAYS)

    raw_events = _raw_dates(logs, "stop_events")
    days = sorted({x + timedelta(days=k) for x in raw_events for k in (-1, 0, 1)})
    for day in days:
        if day > last_settled:
            continue
        ev_path = hist / "stop_events" / f"{day}.parquet"
        agg_path = hist / "delays" / f"{day}.parquet"
        if ev_path.exists() and agg_path.exists():
            continue
        try:
            ev = stop_events(logs, day)
            agg = delays(ev, day)
            for p in (ev_path, agg_path):
                p.parent.mkdir(parents=True, exist_ok=True)
            # The delays file is written last: its presence means the day is done.
            _atomic_write(ev, ev_path, compression="zstd")
            _atomic_write(agg, agg_path, compression="zstd")
            log.info("kept %s: %d stop events, %d delay buckets", day, ev.num_rows, agg.num_rows)
        except Exception:
            log.exception("failed to keep the stop events of %s", day)

    cutoff = now.date() - timedelta(days=RAW_DAYS)
    for dataset in DATASETS:
        for d in _raw_dates(logs, dataset):
            if d >= cutoff:
                continue
            if dataset == "stop_events" and not all(
                (hist / "delays" / f"{d + timedelta(days=k)}.parquet").exists() for k in (-1, 0, 1)
            ):
                log.warning("keeping raw stop events of %s: not all its service days are kept yet", d)
                continue
            shutil.rmtree(logs / dataset / f"date={d}")
            log.info("deleted raw %s of %s", dataset, d)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=os.environ.get("MHD_DATA_DIR", Path(__file__).resolve().parents[2] / "data"))
    run(Path(ap.parse_args().data_dir))


if __name__ == "__main__":
    main()
