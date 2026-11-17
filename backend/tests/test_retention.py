from datetime import date, datetime, timezone

import pyarrow.parquet as pq

from mhd import retention
from mhd.logger import PollLogger
from mhd.static import TZ

UTC = timezone.utc


def _event(ts, day, trip, line, seq, sched, delay, vehicle="v1"):
    sched = sched.astimezone(UTC)
    return {"ts": ts, "service_date": day, "trip": trip, "line": line, "dir": "0", "seq": seq, "stop": f"s{seq}",
            "scheduled": sched, "actual": datetime.fromtimestamp(sched.timestamp() + delay, UTC),
            "delay_s": delay, "vehicle": vehicle, "final": False}


def _local(*a):
    return datetime(*a, tzinfo=TZ)


def test_finished_days_are_kept_and_old_raw_logs_deleted(tmp_path):
    logger = PollLogger(tmp_path / "logs")
    tue, wed = date(2026, 11, 10), date(2026, 11, 11)
    for ts, rows in [
        (_local(2026, 11, 10, 16, 2, 15), [_event(None, tue, "a", "83", 0, _local(2026, 11, 10, 16, 0), 120)]),
        # Another vehicle later reports the same trip and stop: the first record wins.
        (_local(2026, 11, 10, 16, 3), [_event(None, tue, "a", "83", 0, _local(2026, 11, 10, 16, 0), 180, "v2")]),
        (_local(2026, 11, 10, 16, 12), [_event(None, tue, "a", "83", 1, _local(2026, 11, 10, 16, 5), 400),
                                        _event(None, tue, "b", "83", 0, _local(2026, 11, 10, 16, 8), 0),
                                        _event(None, tue, "b", "83", 1, _local(2026, 11, 10, 16, 9), 75)]),
        # A night trip of Tuesday's service day, logged under Wednesday's UTC date.
        (_local(2026, 11, 11, 1, 31), [_event(None, tue, "n", "N33", 0, _local(2026, 11, 11, 1, 30), 60)]),
        (_local(2026, 11, 11, 8, 0), [_event(None, wed, "c", "83", 0, _local(2026, 11, 11, 8, 0), 30)]),
        (_local(2026, 10, 1, 8, 0), [_event(None, date(2026, 10, 1), "o", "83", 0, _local(2026, 10, 1, 8, 0), 0)]),
    ]:
        logger.log_stop_events(ts, [{**r, "ts": ts} for r in rows])
    for d in ("2026-10-01", "2026-11-10"):
        (tmp_path / "logs" / "vehicles" / f"date={d}").mkdir(parents=True)
        (tmp_path / "logs" / "vehicles" / f"date={d}" / "hour=08.parquet").write_bytes(b"")

    retention.run(tmp_path, now=datetime(2026, 11, 17, 3, 0, tzinfo=UTC))
    hist = tmp_path / "history"

    ev = pq.read_table(hist / "stop_events" / "2026-11-10.parquet").to_pylist()
    assert [(e["trip"], e["seq"], e["delay_s"], e["vehicle"]) for e in ev] == [
        ("a", 0, 120, "v1"), ("a", 1, 400, "v1"), ("b", 0, 0, "v1"), ("b", 1, 75, "v1"), ("n", 0, 60, "v1")]

    agg = {(r["line"], r["bucket"]): r for r in pq.read_table(hist / "delays" / "2026-11-10.parquet").to_pylist()}
    assert set(agg) == {("83", 96), ("N33", 153)}  # 16:00–16:10, and 01:30 the next morning
    r = agg[("83", 96)]
    # Delays 0, 75, 120 and 400 s: an even count, so the median (97.5) isn't a whole second.
    assert (r["events"], r["delay_mean"], r["delay_p50"], r["delay_max"], r["late"]) == (4, 148.8, 98, 400, 1)
    assert 120 <= r["delay_p90"] <= 400

    # Raw logs older than 30 days go, once their stop events are kept; newer ones stay.
    assert (hist / "stop_events" / "2026-10-01.parquet").exists()
    assert sorted(p.name for p in (tmp_path / "logs" / "vehicles").iterdir()) == ["date=2026-11-10"]
    assert sorted(p.name for p in (tmp_path / "logs" / "stop_events").iterdir()) == [
        "date=2026-11-10", "date=2026-11-11"]

    # A second run changes nothing.
    before = (hist / "delays" / "2026-11-10.parquet").stat().st_mtime_ns
    retention.run(tmp_path, now=datetime(2026, 11, 17, 3, 0, tzinfo=UTC))
    assert (hist / "delays" / "2026-11-10.parquet").stat().st_mtime_ns == before
