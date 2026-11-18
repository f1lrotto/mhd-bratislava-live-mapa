from datetime import date, datetime, timedelta, timezone

import pyarrow as pa

from mhd.logger import STOP_EVENT_SCHEMA, _atomic_write
from mhd.speeds import Speeds, runs
from mhd.static import TZ

UTC = timezone.utc


def _local(*a):
    return datetime(*a, tzinfo=TZ)


def _trip(trip, stops, start, sched, actual, polls=None, day=None):
    """Stop events of a trip leaving at local `start`: seconds from it to each stop, scheduled and
    actual; polls: the second each stop was recorded at (default: its actual time)."""
    day = day or start.date()
    polls = polls or actual
    return [
        {"ts": (start + timedelta(seconds=p)).astimezone(UTC), "service_date": day, "trip": trip, "line": "83",
         "dir": "0", "seq": k, "stop": s, "scheduled": (start + timedelta(seconds=sc)).astimezone(UTC),
         "actual": (start + timedelta(seconds=a)).astimezone(UTC), "delay_s": a - sc, "vehicle": "v",
         "final": k == len(stops) - 1}
        for k, (s, sc, a, p) in enumerate(zip(stops, sched, actual, polls))
    ]


def _table(rows):
    return pa.Table.from_pylist(rows, schema=STOP_EVENT_SCHEMA)


def _hops(body):
    return {h["k"]: h for h in body["hops"]}


def test_runs_pair_consecutive_stops_of_a_trip_and_drop_unmeasured_ones():
    t0 = _local(2026, 11, 17, 8, 0)
    rows = (
        _trip("a", ["A", "B", "C", "D"], t0, [0, 60, 120, 180], [0, 90, 150, 240])
        # Trip b passes C and D in the same poll: the vehicle jumped, the time isn't measured.
        + _trip("b", ["A", "B", "C", "D"], t0, [0, 60, 120, 180], [10, 70, 130, 131], polls=[10, 70, 130, 130])
        # Trip c has no event at B (missed), so neither A>B nor B>C is a run, and C>D took far
        # too long (a breakdown, not traffic).
        + [e for e in _trip("c", ["A", "B", "C", "D"], t0, [0, 60, 120, 180], [0, 60, 120, 2000]) if e["stop"] != "B"]
    )
    r = runs(_table(rows[::-1])).to_pylist()  # in any order
    got = sorted((x["from"], x["to"], x["sched_s"], x["actual_s"]) for x in r)
    assert got == [("A", "B", 60, 60), ("A", "B", 60, 90), ("B", "C", 60, 60), ("B", "C", 60, 60), ("C", "D", 60, 90)]


def test_live_counts_the_last_half_hour(tmp_path):
    sp = Speeds(tmp_path)
    now = _local(2026, 11, 17, 8, 0)
    sp.add(_trip("old", ["A", "B"], now - timedelta(minutes=40), [0, 60], [0, 120]))
    sp.add(_trip("new", ["A", "B", "C"], now - timedelta(minutes=10), [0, 60, 150], [0, 120, 180]))
    sp.add(_trip("new2", ["A", "B"], now - timedelta(minutes=5), [0, 60], [0, 60]))
    hops = _hops(sp.live(now))
    assert set(hops) == {"A>B", "B>C"}
    ab = hops["A>B"]
    assert (ab["n"], ab["a"], ab["s"]) == (2, 90, 60)
    # Damped toward the timetable by PRIOR_S: (180 + 60) / (120 + 60).
    assert ab["r"] == 1.33
    assert hops["B>C"]["r"] == 0.8  # 60 s on a 90 s schedule, damped: (60 + 60) / (90 + 60)


def test_typical_uses_the_same_kind_of_day_around_the_time(tmp_path):
    hist = tmp_path / "history" / "stop_events"
    hist.mkdir(parents=True)
    today = date(2026, 11, 17)  # a Tuesday
    days = {
        date(2026, 11, 10): [  # last Tuesday
            _trip("t1", ["A", "B"], _local(2026, 11, 10, 7, 50), [0, 100], [0, 200]),
            _trip("t2", ["A", "B"], _local(2026, 11, 10, 8, 20), [0, 100], [0, 200]),
            _trip("t3", ["A", "B"], _local(2026, 11, 10, 6, 59), [0, 100], [0, 900]),  # before the window
            _trip("t4", ["A", "B"], _local(2026, 11, 10, 8, 30), [0, 100], [0, 900]),  # after it
        ],
        date(2026, 11, 13): [  # Friday, also a workday
            _trip("f1", ["A", "B"], _local(2026, 11, 13, 7, 0), [0, 100], [0, 100]),
        ],
        date(2026, 11, 14): [  # Saturday
            _trip("s1", ["A", "B"], _local(2026, 11, 14, 8, 0), [0, 100], [0, 900]),
        ],
    }
    for d, trips in days.items():
        _atomic_write(_table([e for t in trips for e in t]), hist / f"{d}.parquet")

    sp = Speeds(tmp_path)
    body = sp.typical(_local(2026, 11, 17, 7, 45))
    assert (body["kind"], body["days"], body["from"], body["to"]) == ("workday", 2, "07:00", "08:30")
    ab = _hops(body)["A>B"]
    assert (ab["n"], ab["a"], ab["s"]) == (3, 166.7, 100)

    # Another time of the same day: only the run that left at 08:30.
    body = sp.typical(_local(2026, 11, 17, 7, 45), at=9 * 3600 + 10 * 60)
    assert (body["from"], body["to"]) == ("08:30", "10:00")
    assert body["hops"] == []  # one run is too few to call typical

    sat = sp.typical(datetime.combine(today + timedelta(days=4), datetime.min.time(), TZ).replace(hour=8))
    assert (sat["kind"], sat["days"]) == ("saturday", 1)


def test_geometry_draws_a_street_once_however_many_hops_run_it(tmp_path):
    from tests.test_planner import _write, ll

    street = [list(ll(x)) for x in (0, 250, 500, 750, 1000)]
    stops = {"A": (0, 5, "1"), "B": (520, 6, "2"), "C": (1000, 5, "3"),  # the local line
             "A2": (0, -6, "1"), "C2": (1000, -6, "3"),  # an express from other platforms, skipping B
             "idsbk:X": (0, 20, "r1"), "idsbk:Y": (1000, 20, "r2"),  # a regional line along the street
             "idsbk:P": (0, 500, "r3"), "idsbk:Q": (1000, 500, "r4")}  # and one on another street
    p = _write(tmp_path, stops, {"1": {"0": ["A", "B", "C"]}, "2": {"0": ["A2", "C2"]},
                                 "R": {"0": ["idsbk:X", "idsbk:Y"]}, "R2": {"0": ["idsbk:P", "idsbk:Q"]}}, [],
               shapes={"1": {"0": street}, "2": {"0": street},
                       "R": {"0": [list(ll(0, 15)), list(ll(1000, 15))]},
                       "R2": {"0": [list(ll(0, 500)), list(ll(1000, 500))]}})
    g = Speeds(tmp_path).geometry(p)
    hop = {h["k"]: h for h in g["hops"]}
    assert hop["A>B"]["m"] == 500  # cut at the street vertex nearest B (500 m), not at the platform
    segs = {frozenset(g["hops"][i]["k"] for i in s["h"]): s for s in g["segments"]}
    # The street is two segments, split where the local line stops at B; the express shares both.
    assert set(segs) == {frozenset({"A>B", "A2>C2"}), frozenset({"B>C", "A2>C2"}),
                         frozenset({"idsbk:X>idsbk:Y"}), frozenset({"idsbk:P>idsbk:Q"})}
    rounded = [[round(v, 5) for v in c] for c in street]
    assert segs[frozenset({"A>B", "A2>C2"})]["c"] == rounded[:3]
    assert segs[frozenset({"B>C", "A2>C2"})]["c"] == rounded[2:]
    # The regional line beside the DPB street is left out of the network view; the other isn't.
    assert segs[frozenset({"idsbk:X>idsbk:Y"})].get("o") is True
    assert "o" not in segs[frozenset({"idsbk:P>idsbk:Q"})]
