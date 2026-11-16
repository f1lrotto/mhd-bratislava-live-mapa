import json
from datetime import datetime, timedelta

from mhd import lineview
from mhd.feed import Vehicle
from mhd.geo import to_lonlat, to_xy
from mhd.poller import Poller
from mhd.static import TZ, Static

BASE = to_xy(17.10, 48.15)


def ll(x, y=0.0):
    return to_lonlat(BASE[0] + x, BASE[1] + y)


def _write_static(tmp_path):
    """Line 83: 10 km due east (direction 0) and back (direction 1), 20 min each way.

    Both directions list "Most SNP" as a headsign, so matching must use the heading."""
    east = [list(ll(0)), list(ll(10_000))]
    d = tmp_path / "static"
    d.mkdir()
    stops = {"A": {"name": "Západ", "lat": ll(0)[1], "lon": ll(0)[0], "lines": ["83"]},
             "B": {"name": "Východ", "lat": ll(10_000)[1], "lon": ll(10_000)[0], "lines": ["83"]},
             "M": {"name": "Stred", "lat": ll(5000)[1], "lon": ll(5000)[0], "lines": ["83"]}}
    lines = {"83": {"line": "83", "type": "bus", "color": "#000", "textColor": "#fff", "directions": {
        "0": {"headsign": "Východ", "headsigns": ["Most SNP", "Východ"], "from": "Západ", "stops": ["A", "M", "B"],
              "stopDist": [0, 5000, 10_000], "length": 10_000, "duration": 1200},
        "1": {"headsign": "Západ", "headsigns": ["Most SNP", "Západ"], "from": "Východ", "stops": ["B", "A"],
              "stopDist": [0, 10_000], "length": 10_000, "duration": 1200},
    }}}
    weekday = {"days": [1, 1, 1, 1, 1, 0, 0], "start": "20261101", "end": "20271231"}
    service = {
        "calendar": {
            "work": {**weekday, "added": [], "removed": ["20261117"]},
            # Same weekday pattern but switched off today: its departures must not count.
            "summer": {**weekday, "added": [], "removed": ["20261116"]},
        },
        "departures": {"83": {
            # 16:00, 16:10, 16:20, ... (every 10 min) plus a trip of yesterday's day at 24:30.
            "0": {"work": [16 * 3600 + i * 600 for i in range(12)] + [24 * 3600 + 1800],
                  "summer": [16 * 3600 + 300 + i * 600 for i in range(6)]},
            "1": {"work": [0 * 3600 + 15 * 60, 0 * 3600 + 45 * 60]},
        }},
    }
    shapes = {"83": {"0": east, "1": east[::-1]}}
    for name, obj in [("meta", {"feedVersion": "t"}), ("lines", lines), ("stops", stops),
                      ("service", service), ("shapes", shapes)]:
        (d / f"{name}.json").write_text(json.dumps(obj))
    return Static.load(tmp_path)


MON_1630 = datetime(2026, 11, 16, 16, 30, tzinfo=TZ)


def test_interval_uses_only_services_active_today(tmp_path):
    s = _write_static(tmp_path)
    assert s.active_services(MON_1630.date()) == {"work"}
    # "summer" departures would halve the interval to 5 min if the removed date were ignored.
    assert s.scheduled_interval("83", "0", MON_1630) == 600
    # Tuesday has "work" removed and "summer" on: 16:05, 16:15, ... still every 10 min.
    assert s.scheduled_interval("83", "0", MON_1630 + timedelta(days=1)) == 600
    assert s.scheduled_interval("83", "0", MON_1630.replace(hour=3)) is None


def test_interval_includes_trips_after_midnight_from_yesterday(tmp_path):
    s = _write_static(tmp_path)
    # Wednesday 00:10: direction 1 has 00:15 and 00:45 (30 min apart).
    wed_0010 = datetime(2026, 11, 18, 0, 10, tzinfo=TZ)
    assert s.scheduled_interval("83", "1", wed_0010) == 1800
    # Monday's 24:30 trip of direction 0 runs at 00:30 on Tuesday, a day with no service of its own.
    tue_0010 = datetime(2026, 11, 17, 0, 10, tzinfo=TZ)
    assert 1800 in s.departures_around("83", "0", tue_0010)


def test_ambiguous_headsign_is_matched_by_heading(tmp_path):
    s = _write_static(tmp_path)
    lon, lat = ll(5000, 5)
    assert s.match_direction("83", "Most SNP", lon, lat, 90)[0].id == "0"
    assert s.match_direction("83", "Most SNP", lon, lat, 270)[0].id == "1"
    assert s.match_direction("83", "Depo Petržalka", lon, lat, 90) is None


def _bus(key, x, delay=60, dest="Východ"):
    lon, lat = ll(x, 3)
    return Vehicle(key, "83", dest, "bus", lat, lon, delay, 1, 90)


def test_line_view_orders_vehicles_and_flags_gaps_and_bunching(tmp_path):
    s = _write_static(tmp_path)
    p = Poller(logger=None)
    # Speed is 10 km / 20 min = 8.33 m/s, interval 600 s: gap > 900 s (7.5 km), bunched < 180 s (1.5 km).
    vs = [
        _bus("c", 9000), _bus("a", 500), _bus("b", 1000),  # a→b 500 m = 60 s: bunched
        _bus("depot", 2000, dest="Depo Petržalka"),
        _bus("t", 9950),  # laying over at the far terminus
    ]
    p.apply(vs, MON_1630)
    derived = lineview.derive_poll(p.snapshot, s)
    view = lineview.line_view("83", p.snapshot, derived, s, MON_1630)
    d0 = view["directions"][0]
    assert [v["key"] for v in d0["vehicles"]] == ["a", "b", "c", "t"]
    flags = {v["key"]: v.get("gapAhead", {}).get("flag") for v in d0["vehicles"]}
    # b→c is 8 km = 960 s: a gap. c→t is 950 m, but t is at the terminus, so no bunching flag.
    assert flags == {"a": "bunched", "b": "gap", "c": None, "t": None}
    assert d0["interval"] == 600 and d0["summary"]["gaps"] == 1 and d0["summary"]["bunched"] == 1
    # The gap runs from b (last stop Západ) to c (last stop Stred).
    assert d0["summary"]["biggestGap"] == {"s": 960, "fromStop": "Západ", "afterStop": "Stred"}
    assert d0["branches"] == []
    assert view["unmatched"] == [{"key": "depot", "dest": "Depo Petržalka", "reason": "to_depot"}]


def test_city_status_worst_lines_need_three_vehicles(tmp_path):
    s = _write_static(tmp_path)
    p = Poller(logger=None)
    lone = Vehicle("x", "39", "Y", "bus", 48.15, 17.1, 900, 2, None)
    p.apply([_bus("a", 100, 0), _bus("b", 200, 240), _bus("c", 300, 600), lone], MON_1630)
    st = lineview.city_status(p.snapshot, lineview.derive_poll(p.snapshot, s), s, MON_1630)
    assert [w["line"] for w in st["worst"]] == ["83"]
    assert st["worst"][0]["medianDelay"] == 240
    assert st["shareLate"] == 0.75


def test_parked_vehicles_get_no_flags_and_leave_city_status(tmp_path):
    s = _write_static(tmp_path)
    p = Poller(logger=None)
    # Two buses parked 100 m apart mid-route (a depot beside the road), plus one running.
    parked = [_bus("p1", 5000, 900), _bus("p2", 5100, 900)]
    p.apply(parked + [_bus("r", 2000, 0)], MON_1630)
    later = MON_1630 + timedelta(minutes=11)
    p.apply(parked + [_bus("r", 3000, 0)], later)
    derived = lineview.derive_poll(p.snapshot, s)
    d0 = lineview.line_view("83", p.snapshot, derived, s, later)["directions"][0]
    assert d0["summary"]["count"] == 1 and d0["summary"]["bunched"] == 0
    assert d0["summary"]["medianDelay"] == 0
    st = lineview.city_status(p.snapshot, derived, s, later)
    assert st["vehicles"] == 1 and st["shareLate"] == 0


def test_history_buckets_by_local_wall_clock_on_dst_day(tmp_path):
    from datetime import timezone

    from mhd.history import day_curve
    from mhd.logger import PollLogger

    lg = PollLogger(tmp_path)
    # 31 Oct 2027 has 25 hours in Bratislava. 22:05 local is 21:05 UTC (after the change to CET).
    ts = datetime(2027, 10, 31, 21, 5, tzinfo=timezone.utc)
    lg.log_poll(ts, [_bus("a", 100, 300), _bus("b", 200, 0)], 10, None)
    lg.compact_finished(now=ts + timedelta(hours=3))
    from datetime import date

    assert day_curve(tmp_path, date(2027, 10, 31)) == {22 * 6: 0.5}


def test_vehicle_on_a_branch_is_on_route_but_gets_no_gaps(tmp_path):
    _write_static(tmp_path)
    # A branch of direction 0 that joins the main route at 2 km from 2 km north.
    branch = [list(ll(2000, 2000)), list(ll(2000, 0)), list(ll(10_000))]
    (tmp_path / "static" / "branches.json").write_text(json.dumps({"83": {"0": [branch]}}))
    s = Static.load(tmp_path)
    p = Poller(logger=None)
    lon, lat = ll(2005, 1500)
    p.apply([Vehicle("br", "83", "Východ", "bus", lat, lon, 0, 1, 180), _bus("a", 2500)], MON_1630)
    derived = lineview.derive_poll(p.snapshot, s)
    d0 = lineview.line_view("83", p.snapshot, derived, s, MON_1630)["directions"][0]
    assert d0["branches"] == [branch]
    br = next(v for v in d0["vehicles"] if v["key"] == "br")
    assert br["onBranch"] and not br["offRoute"] and "gapAhead" not in br
    assert d0["summary"]["count"] == 1
    assert lineview.city_status(p.snapshot, derived, s, MON_1630)["vehicles"] == 2
