"""Share of DPB's trips running late through the day, from the logged stop events.

Stop events only exist for vehicles running a trip, so parked and depot-bound vehicles, whose
reported delay means nothing, don't count. Each stop a trip passes counts once.

Today's curves (2+ and 5+ min late) and the median of the last four same weekdays (5+ min), in
10-minute buckets of local time. The baseline only exists once all four of those days have logs.
"""

from __future__ import annotations

import logging
import statistics
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from .derive import LATE_S
from .feed import REGIONAL
from .static import TZ

log = logging.getLogger(__name__)

DELAYED_S = 2 * 60  # where derive.delay_band stops calling a delay on time
BUCKET_S = 600
BASELINE_WEEKS = 4
MIN_DAY_COVERAGE = 0.5  # a day needs logs in at least half its buckets to count


def _files_for_local_day(root: Path, day: date) -> list[Path]:
    start = datetime.combine(day, time(0), TZ).astimezone(timezone.utc)
    end = datetime.combine(day + timedelta(days=1), time(0), TZ).astimezone(timezone.utc)
    files = []
    h = start.replace(minute=0, second=0, microsecond=0)
    while h < end:
        d = root / "stop_events" / f"date={h:%Y-%m-%d}"
        files += [p for p in d.glob(f"hour={h:%H}*.parquet")] if d.exists() else []
        h += timedelta(hours=1)
    return files


def day_curves(root: Path, day: date) -> dict[str, dict[int, float]]:
    """bucket index (0..143) -> share of DPB's stop passes at least DELAYED_S ("delayed") and
    LATE_S ("late") late."""
    tables = []
    for f in _files_for_local_day(root, day):
        try:
            tables.append(pq.read_table(f, columns=["ts", "vehicle", "delay_s"]))
        except Exception:
            log.exception("unreadable log file %s", f)
    if not tables:
        return {"delayed": {}, "late": {}}
    t = pa.concat_tables(tables)
    t = t.filter(pc.invert(pc.starts_with(t["vehicle"], REGIONAL)))
    # One row per poll instead of one per stop passed, then bucket each poll by its local
    # wall-clock time, so DST days line up with normal days.
    per_poll = (
        pa.table(
            {
                "ts": t["ts"],
                "delayed": pc.cast(pc.greater_equal(t["delay_s"], DELAYED_S), pa.int32()),
                "late": pc.cast(pc.greater_equal(t["delay_s"], LATE_S), pa.int32()),
            }
        )
        .group_by("ts")
        .aggregate([("delayed", "sum"), ("late", "sum"), ("late", "count")])
    )
    totals: dict[int, list[int]] = {}
    for ts, n_delayed, n_late, n in zip(
        per_poll["ts"].to_pylist(),
        per_poll["delayed_sum"].to_pylist(),
        per_poll["late_sum"].to_pylist(),
        per_poll["late_count"].to_pylist(),
    ):
        local = ts.astimezone(TZ)
        if local.date() != day:
            continue
        b = (local.hour * 3600 + local.minute * 60 + local.second) // BUCKET_S
        c = totals.setdefault(b, [0, 0, 0])
        c[0] += n_delayed
        c[1] += n_late
        c[2] += n
    return {
        "delayed": {b: round(c[0] / c[2], 3) for b, c in totals.items() if c[2]},
        "late": {b: round(c[1] / c[2], 3) for b, c in totals.items() if c[2]},
    }


class History:
    def __init__(self, root: Path):
        self.root = root
        self._baseline: tuple[date, dict[int, float] | None] | None = None
        self._today: tuple[date, float, dict[str, dict[int, float]]] | None = None

    def baseline(self, day: date) -> dict[int, float] | None:
        if self._baseline and self._baseline[0] == day:
            return self._baseline[1]
        curves = []
        for w in range(1, BASELINE_WEEKS + 1):
            c = day_curves(self.root, day - timedelta(weeks=w))["late"]
            if len(c) < MIN_DAY_COVERAGE * (86400 // BUCKET_S):
                curves = None
                break
            curves.append(c)
        result = None
        if curves:
            buckets = set().union(*curves)
            result = {
                b: round(statistics.median([c[b] for c in curves if b in c]), 3)
                for b in sorted(buckets)
                if sum(b in c for c in curves) >= 3
            }
        self._baseline = (day, result)
        return result

    def today(self, now: datetime) -> dict[str, dict[int, float]]:
        """Recomputed from the logs at most every 5 minutes."""
        day = now.astimezone(TZ).date()
        ts = now.timestamp()
        if self._today and self._today[0] == day and ts - self._today[1] < 300:
            return self._today[2]
        curves = day_curves(self.root, day)
        self._today = (day, ts, curves)
        return curves

    def status(self, now: datetime) -> dict:
        day = now.astimezone(TZ).date()
        today = self.today(now)
        return {
            "bucketS": BUCKET_S,
            "today": today["late"],
            "todayDelayed": today["delayed"],
            "baseline": self.baseline(day),
        }
