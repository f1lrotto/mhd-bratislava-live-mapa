"""Map replay: the logged positions of a past 10-minute window, for the frontend to play back.

Replay reads the raw logs (logger.py), so it covers what retention keeps of them: the last
retention.RAW_DAYS days. What is kept forever (stop events and delay aggregates) has no positions
between stops, so older days can't be replayed. Nothing is stored for replay and nothing is kept in
memory between requests: a chunk reads at most two hour files per dataset, and the server reads at
most MAX_READERS chunks at once, so a burst of scrubbing can't run it out of memory.

A chunk is one track per vehicle: its samples from MARGIN_S before the chunk to MARGIN_S after it
(so the client can interpolate across the chunk's edges without its neighbours), delta-encoded:

    t     seconds after the chunk's start; the first absolute, then differences
    lat   latitude in 1e-5 degrees, the same way; lon likewise
    d     the reported delay in seconds (null: none)
    az    the heading in degrees (null: none)
    line, dest   indexes into the chunk's `strings` (0 is "none")
    run   1 while the vehicle runs a trip (between the first and the last stop it passed on the trip,
          from the stop events), 0 otherwise: as in the live view, only running vehicles show their
          delay. Absent when the window has no stop events at all (logs from before they were
          recorded), and then every vehicle shows its delay.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from .logger import _hour_dir
from .retention import RAW_DAYS

CHUNK_S = 600
MARGIN_S = 120
# Stop events this far around the chunk tell which vehicles run a trip: a trip's consecutive stops
# are a few minutes apart, so a vehicle between two of them always has one on each side.
TRIP_GAP_S = 20 * 60
# A chunk is final once its last sample can't change any more (part files are written each poll).
SETTLE_S = 120
MAX_READERS = 2

_VEHICLE_COLUMNS = ["ts", "key", "line", "dest", "type", "lat", "lon", "delay_s", "azimuth"]


def _read(root: Path, dataset: str, a: datetime, b: datetime, columns: list[str]) -> pa.Table | None:
    """Rows of a dataset with a <= ts < b, from its hour files and the current hour's part files."""
    tables = []
    h = a.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    while h < b:
        d, hour = _hour_dir(root, dataset, h)
        for attempt in range(2):
            # The logger may compact the hour between the glob and the read; then look again.
            try:
                files = sorted(d.glob(f"{hour}.parquet")) + sorted(d.glob(f"{hour}.part-*.parquet"))
                tables += [pq.read_table(f, columns=columns) for f in files]
                break
            except FileNotFoundError:
                if attempt:
                    raise
        h += timedelta(hours=1)
    if not tables:
        return None
    t = pa.concat_tables(tables)
    ts = t["ts"]
    return t.filter(pc.and_(pc.greater_equal(ts, pa.scalar(a, ts.type)), pc.less(ts, pa.scalar(b, ts.type))))


def _running(root: Path, a: datetime, b: datetime) -> dict[str, list[tuple[float, float]]] | None:
    """Vehicle key -> the intervals it ran a trip in, from the first to the last stop it passed."""
    ev = _read(root, "stop_events", a - timedelta(seconds=TRIP_GAP_S), b + timedelta(seconds=TRIP_GAP_S),
               ["ts", "trip", "vehicle"])
    if ev is None or not ev.num_rows:
        return None
    g = ev.group_by(["vehicle", "trip"]).aggregate([("ts", "min"), ("ts", "max")])
    out: dict[str, list[tuple[float, float]]] = {}
    for key, lo, hi in zip(g["vehicle"].to_pylist(), g["ts_min"].to_pylist(), g["ts_max"].to_pylist()):
        out.setdefault(key, []).append((lo.timestamp(), hi.timestamp()))
    return out


def chunk(root: Path, t: int, now: datetime | None = None) -> dict:
    """The chunk holding Unix time t."""
    now = now or datetime.now(timezone.utc)
    start = t - t % CHUNK_S
    a = datetime.fromtimestamp(start - MARGIN_S, timezone.utc)
    b = datetime.fromtimestamp(start + CHUNK_S + MARGIN_S, timezone.utc)
    parts = [x for x in (_read(root, ds, a, b, _VEHICLE_COLUMNS) for ds in ("vehicles", "regional_vehicles")) if x is not None]
    running = _running(root, a, b)
    strings = {"": 0}
    vehicles = []
    if parts:
        rows = pa.concat_tables(parts).sort_by([("key", "ascending"), ("ts", "ascending")]).to_pydict()
        cur = None
        for i, key in enumerate(rows["key"]):
            ts = rows["ts"][i].timestamp()
            lat, lon = round(rows["lat"][i] * 1e5), round(rows["lon"][i] * 1e5)
            # Read while the logger compacted the hour, a poll is in both the hour file and its part.
            if cur is not None and cur["key"] == key and round(ts - prev[0]) == 0:
                continue
            if cur is None or cur["key"] != key:
                cur = {"key": key, "type": rows["type"][i], "t": [], "lat": [], "lon": [], "d": [], "az": [],
                       "line": [], "dest": []}
                if running is not None:
                    cur["run"] = []
                vehicles.append(cur)
                prev = (start, 0, 0)
            cur["t"].append(round(ts - prev[0]))
            cur["lat"].append(lat - prev[1])
            cur["lon"].append(lon - prev[2])
            prev = (prev[0] + cur["t"][-1], lat, lon)
            cur["d"].append(rows["delay_s"][i])
            cur["az"].append(rows["azimuth"][i])
            for f in ("line", "dest"):
                s = rows[f][i] or ""
                cur[f].append(strings.setdefault(s, len(strings)))
            if running is not None:
                cur["run"].append(int(any(lo <= ts <= hi for lo, hi in running.get(key, ()))))
    return {
        "start": start,
        "end": start + CHUNK_S,
        "complete": now.timestamp() >= start + CHUNK_S + MARGIN_S + SETTLE_S,
        "strings": list(strings),
        "vehicles": vehicles,
    }


def available(root: Path, now: datetime | None = None) -> dict:
    """What replay covers: every UTC hour with logged DPB positions (Unix times of the hours'
    starts), from the oldest one retention still keeps until now."""
    now = now or datetime.now(timezone.utc)
    hours = set()
    for f in (root / "vehicles").glob("date=*/hour=*.parquet"):
        hours.add(int(datetime.fromisoformat(f"{f.parent.name[5:]}T{f.name[5:7]}:00:00+00:00").timestamp()))
    return {"now": now.isoformat(), "chunkS": CHUNK_S, "rawDays": RAW_DAYS, "hours": sorted(hours)}
