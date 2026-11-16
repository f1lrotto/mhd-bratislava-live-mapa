"""Share of vehicles running 3+ min late through the day, from the poll logs.

Today's curve and the median of the last four same weekdays, in 10-minute buckets of local time.
The baseline only exists once all four of those days have logs.
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
from .static import TZ

log = logging.getLogger(__name__)

BUCKET_S = 600
BASELINE_WEEKS = 4
MIN_DAY_COVERAGE = 0.5  # a day needs logs in at least half its buckets to count


def _files_for_local_day(root: Path, day: date) -> list[Path]:
    start = datetime.combine(day, time(0), TZ).astimezone(timezone.utc)
    end = datetime.combine(day + timedelta(days=1), time(0), TZ).astimezone(timezone.utc)
    files = []
    h = start.replace(minute=0, second=0, microsecond=0)
    while h < end:
        d = root / "vehicles" / f"date={h:%Y-%m-%d}"
        files += [p for p in d.glob(f"hour={h:%H}*.parquet")] if d.exists() else []
        h += timedelta(hours=1)
    return files


def day_curve(root: Path, day: date) -> dict[int, float]:
    """bucket index (0..143) -> share late among vehicles with a line and a delay."""
    files = _files_for_local_day(root, day)
    if not files:
        return {}
    tables = []
    for f in files:
        try:
            tables.append(pq.read_table(f, columns=["ts", "line", "delay_s"]))
        except Exception:
            log.exception("unreadable log file %s", f)
    if not tables:
        return {}
    t = pa.concat_tables(tables)
    t = t.filter(pc.and_(pc.is_valid(t["line"]), pc.is_valid(t["delay_s"])))
    if t.num_rows == 0:
        return {}
    midnight = datetime.combine(day, time(0), TZ).timestamp()
    secs = pc.divide(pc.cast(t["ts"], pa.int64()), 1000).to_pylist()
    late = pc.greater_equal(t["delay_s"], LATE_S).to_pylist()
    totals: dict[int, list[int]] = {}
    for s, is_late in zip(secs, late):
        b = int((s - midnight) // BUCKET_S)
        if 0 <= b < 86400 // BUCKET_S:
            c = totals.setdefault(b, [0, 0])
            c[0] += int(is_late)
            c[1] += 1
    return {b: round(c[0] / c[1], 3) for b, c in totals.items() if c[1]}


class History:
    def __init__(self, root: Path):
        self.root = root
        self._baseline: tuple[date, dict[int, float] | None] | None = None
        self._today: tuple[date, float, dict[int, float]] | None = None

    def baseline(self, day: date) -> dict[int, float] | None:
        if self._baseline and self._baseline[0] == day:
            return self._baseline[1]
        curves = []
        for w in range(1, BASELINE_WEEKS + 1):
            c = day_curve(self.root, day - timedelta(weeks=w))
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

    def today(self, now: datetime) -> dict[int, float]:
        """Recomputed from the logs at most every 5 minutes."""
        day = now.astimezone(TZ).date()
        ts = now.timestamp()
        if self._today and self._today[0] == day and ts - self._today[1] < 300:
            return self._today[2]
        curve = day_curve(self.root, day)
        self._today = (day, ts, curve)
        return curve

    def status(self, now: datetime) -> dict:
        day = now.astimezone(TZ).date()
        return {"bucketS": BUCKET_S, "today": self.today(now), "baseline": self.baseline(day)}
