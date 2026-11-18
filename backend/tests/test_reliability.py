from datetime import date, datetime, timedelta, timezone

import pyarrow as pa
import pyarrow.parquet as pq
from test_lineview import _write_static

from mhd import retention
from mhd.logger import STOP_EVENT_SCHEMA
from mhd.reliability import line_reliability
from mhd.static import TZ

UTC = timezone.utc
STOPS = {"0": ["A", "M", "B"], "1": ["B", "A"]}


def _trip(day, trip, d, start, delays, first=0):
    """Events of a trip of line 83 starting at `start` (local) at stop index `first`, 10 min per stop."""
    out = []
    for i, delay in enumerate(delays):
        sched = (start + timedelta(minutes=10 * i)).astimezone(UTC)
        out.append({"ts": sched, "service_date": day, "trip": trip, "line": "83", "dir": d, "seq": i,
                    "stop": STOPS[d][first + i], "scheduled": sched, "actual": sched + timedelta(seconds=delay),
                    "delay_s": delay, "vehicle": "v", "final": False})
    return out


def _keep(hist, day, events, complete=True):
    ev = pa.Table.from_pylist(events, schema=STOP_EVENT_SCHEMA)
    for sub in ("stop_events", "delays"):
        (hist / sub).mkdir(parents=True, exist_ok=True)
    pq.write_table(ev, hist / "stop_events" / f"{day}.parquet")
    if complete:
        pq.write_table(retention.delays(ev, day), hist / "delays" / f"{day}.parquet")


def _at(day, h, m=0):
    return datetime(day.year, day.month, day.day, tzinfo=TZ) + timedelta(hours=h, minutes=m)


def test_delays_by_stop_and_hour_and_late_trips(tmp_path):
    static = _write_static(tmp_path)
    hist = tmp_path / "history"
    mon, tue, wed, sat = date(2026, 11, 9), date(2026, 11, 10), date(2026, 11, 11), date(2026, 11, 14)
    ev = []
    # Five trips A 16:0x → M → B, later and later at B (100…500 s late).
    for i in range(5):
        ev += _trip(mon, f"t{i}", "0", _at(mon, 16, i), [0, 60, 100 * (i + 1)])
    # A short trip from M: its first stop is the direction's second.
    ev += _trip(mon, "s", "0", _at(mon, 16, 20), [0, 600], first=1)
    # A night trip of Monday's service day, after midnight: hour 24. One pass: too few for a value.
    ev += _trip(mon, "n", "0", _at(mon, 24, 30), [30])
    _keep(hist, mon, ev)
    # The same trip id on another day is another trip.
    _keep(hist, tue, _trip(tue, "t0", "0", _at(tue, 16), [0]))
    # Not kept completely yet (no delays file), a weekend, and a day older than the four weeks.
    _keep(hist, wed, _trip(wed, "x", "0", _at(wed, 16), [900, 900, 900]), complete=False)
    _keep(hist, sat, _trip(sat, "w", "1", _at(sat, 9), [0, 400]))
    _keep(hist, date(2026, 10, 12), _trip(date(2026, 10, 12), "o", "0", _at(date(2026, 10, 12), 16), [900]))

    r = line_reliability(hist, static, "83", "workdays")
    assert r["days"] == {"count": 2, "from": "2026-11-09", "to": "2026-11-10"}
    # 8 trips (t0 on two days); t2, t3, t4 and s were 5+ min late somewhere. 19 passes: the median
    # is the 10th (60 s), p90 the 18th (500 s).
    assert r["summary"] == {"passes": 19, "trips": 8, "p50": 60, "p90": 500, "lateTrips": 0.5}

    d0 = r["directions"][0]
    assert (d0["id"], d0["stops"], d0["hours"]) == ("0", ["Západ", "Stred", "Východ"], list(range(16, 25)))
    assert [row[0] for row in d0["median"]] == [0, 60, 350]
    assert [row[0] for row in d0["n"]] == [6, 6, 6]
    assert d0["p90"][2][0] == 600 and d0["late"][2][0] == 0.667
    assert (d0["n"][0][-1], d0["median"][0][-1]) == (1, None)
    assert d0["stopMedian"] == [0, 60, 350]
    assert r["directions"][1]["summary"]["trips"] == 0

    w = line_reliability(hist, static, "83", "weekends")
    assert w["days"]["count"] == 1
    assert w["summary"] == {"passes": 2, "trips": 1, "p50": 0, "p90": 400, "lateTrips": 1.0}
    assert line_reliability(hist, static, "99", "workdays") is None
