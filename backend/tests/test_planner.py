import json
from datetime import datetime

from mhd.geo import to_lonlat, to_xy
from mhd.planner import Planner, TZ

BASE = to_xy(17.10, 48.15)
MON = (2026, 11, 16)


def ll(x, y=0.0):
    """lon, lat of a point x m east and y m north of the base."""
    return to_lonlat(BASE[0] + x, BASE[1] + y)


def hms(h, m, s=0):
    return h * 3600 + m * 60 + s


def at(h, m, s=0, day=MON):
    return datetime(*day, h, m, s, tzinfo=TZ)


def iso(h, m, s=0, day=MON):
    return at(h, m, s, day).isoformat()


def _write(tmp_path, stops, lines, trips, calendar=None, shapes=None):
    """stops: {id: (x, y, station)}; lines: {line: {dir: [stop ids]}} (one pattern per direction);
    trips: [(id, line, dir, svc, [times])]."""
    d = tmp_path / "static"
    d.mkdir()
    stops_j, stations = {}, {}
    for sid, (x, y, st) in stops.items():
        lon, lat = ll(x, y)
        stops_j[sid] = {"name": f"Stop {st or sid}", "code": st, "platform": sid, "lat": lat, "lon": lon,
                        "lines": [], "station": st}
        if st:
            s = stations.setdefault(st, {"name": f"Stop {st}", "lat": lat, "lon": lon, "stops": [], "lines": []})
            s["stops"].append(sid)
    patterns, index = [], {}
    for line, dirs in lines.items():
        for dr, seq in dirs.items():
            index[(line, dr)] = len(patterns)
            patterns.append({"line": line, "dir": dr, "stops": seq})
    timetable = {"patterns": patterns,
                 "trips": [{"id": tid, "p": index[(line, dr)], "svc": svc, "head": "End", "t": t}
                           for tid, line, dr, svc, t in trips]}
    lines_j = {line: {"line": line, "type": "bus", "color": "#123456", "textColor": "#FFFFFF",
                      "directions": {dr: {"headsign": "End", "stops": seq} for dr, seq in dirs.items()}}
               for line, dirs in lines.items()}
    if shapes is None:  # straight shapes through the stops
        shapes = {line: {dr: [list(ll(*stops[s][:2])) for s in seq] for dr, seq in dirs.items()}
                  for line, dirs in lines.items()}
    calendar = calendar or {"work": {"days": [1, 1, 1, 1, 1, 0, 0], "start": "20261101", "end": "20271231",
                                     "added": [], "removed": []}}
    files = {"stops": stops_j, "stations": stations, "timetable": timetable, "lines": lines_j,
             "shapes": shapes, "branches": {}, "service": {"calendar": calendar, "departures": {}}}
    for name, obj in files.items():
        (d / f"{name}.json").write_text(json.dumps(obj))
    return Planner(d)


def rides(it):
    return [leg for leg in it["legs"] if leg["kind"] == "ride"]


def test_direct_ride_beats_transfer_and_follows_the_shape(tmp_path):
    stops = {"A": (0, 0, "1"), "B": (5000, 0, "2"), "C": (10_000, 0, "3")}
    bend = list(ll(5000, 100))  # line 1 bends 100 m north of B
    shapes = {"1": {"0": [list(ll(0)), bend, list(ll(10_000))]},
              "2": {"0": [list(ll(0)), list(ll(5000))]}, "3": {"0": [list(ll(5000)), list(ll(10_000))]}}
    p = _write(tmp_path, stops, {"1": {"0": ["A", "C"]}, "2": {"0": ["A", "B"]}, "3": {"0": ["B", "C"]}}, [
        ("direct", "1", "0", "work", [hms(8, 0), hms(8, 20)]),
        ("first", "2", "0", "work", [hms(8, 0), hms(8, 10)]),
        ("second", "3", "0", "work", [hms(8, 12), hms(8, 22)]),
    ], shapes=shapes)
    res = p.plan({"station": "1"}, {"station": "3"}, at(7, 55))
    best = res[0]
    assert [r["trip"] for r in rides(best)] == ["direct"]
    assert best["transfers"] == 0 and best["depart"] == iso(8, 0) and best["arrive"] == iso(8, 20)
    assert best["duration"] == 1200 and best["walkM"] == 0 and len(best["legs"]) == 1
    assert all(it["transfers"] == 0 for it in res)  # the slower transfer is not offered
    ride = rides(best)[0]
    assert [s["stop"] for s in ride["stops"]] == ["A", "C"]
    assert ride["delay"] is None and ride["line"] == "1" and ride["dir"] == "0" and ride["headsign"] == "End"
    assert len(ride["coords"]) == 3 and ride["coords"][1] == [round(c, 6) for c in bend]


def test_platform_change_needs_the_walk(tmp_path):
    # Station 2 has platforms P and Q 30 m apart: the change takes the 60 s minimum.
    stops = {"A": (0, 0, "1"), "P": (5000, 0, "2"), "Q": (5000, 30, "2"), "C": (5000, 5000, "3")}
    p = _write(tmp_path, stops, {"1": {"0": ["A", "P"]}, "2": {"0": ["Q", "C"]}}, [
        ("in", "1", "0", "work", [hms(8, 0), hms(8, 10)]),
        ("too_soon", "2", "0", "work", [hms(8, 10, 45), hms(8, 20)]),
        ("ok", "2", "0", "work", [hms(8, 11, 30), hms(8, 21)]),
    ])
    best = p.plan({"station": "1"}, {"station": "3"}, at(7, 59))[0]
    assert [r["trip"] for r in rides(best)] == ["in", "ok"]
    assert [leg["kind"] for leg in best["legs"]] == ["ride", "walk", "ride"]
    walk = best["legs"][1]
    assert walk["from"]["stop"] == "P" and walk["to"]["stop"] == "Q"
    assert walk["start"] == iso(8, 10) and walk["end"] == iso(8, 11)
    assert best["transfers"] == 1 and best["arrive"] == iso(8, 21)


def test_delay_on_first_trip_picks_another(tmp_path):
    stops = {"A": (0, 0, "1"), "B": (5000, 0, "2")}
    p = _write(tmp_path, stops, {"1": {"0": ["A", "B"]}}, [
        ("early", "1", "0", "work", [hms(8, 5), hms(8, 15)]),
        ("late", "1", "0", "work", [hms(8, 15), hms(8, 25)]),
    ])
    o, d = {"station": "1"}, {"station": "2"}
    assert rides(p.plan(o, d, at(8, 0))[0])[0]["trip"] == "early"
    # 15 min late: the next trip arrives earlier.
    best = p.plan(o, d, at(8, 0), delays={"early": 900})[0]
    assert rides(best)[0]["trip"] == "late" and rides(best)[0]["delay"] is None
    assert best["arrive"] == iso(8, 25)
    # 5 min late: still the first to arrive, at its realtime.
    best = p.plan(o, d, at(8, 0), delays={"early": 300})[0]
    ride = rides(best)[0]
    assert ride["trip"] == "early" and ride["delay"] == 300
    assert ride["start"] == iso(8, 10) and best["arrive"] == iso(8, 20)
    assert [s["time"] for s in ride["stops"]] == [iso(8, 10), iso(8, 20)]
    # A trip that already left (sched 8:05 < 8:08) is caught when it runs 5 min late.
    assert rides(p.plan(o, d, at(8, 8), delays={"early": 300})[0])[0]["trip"] == "early"


def test_trip_after_midnight_from_yesterdays_service(tmp_path):
    stops = {"A": (0, 0, "1"), "B": (5000, 0, "2")}
    calendar = {"sun": {"days": [0, 0, 0, 0, 0, 0, 1], "start": "20261101", "end": "20271231",
                        "added": [], "removed": []},
                "work": {"days": [1, 1, 1, 1, 1, 0, 0], "start": "20261101", "end": "20271231",
                         "added": [], "removed": []}}
    p = _write(tmp_path, stops, {"1": {"0": ["A", "B"]}}, [
        ("night", "1", "0", "sun", [hms(24, 30), hms(24, 40)]),  # Sunday's day, Monday 00:30
        ("night_mon", "1", "0", "work", [hms(24, 50), hms(25, 0)]),  # Monday's day, Tuesday 00:50
        ("morning", "1", "0", "work", [hms(5, 0), hms(5, 10)]),
    ], calendar=calendar)
    res = p.plan({"station": "1"}, {"station": "2"}, at(0, 20))
    assert rides(res[0])[0]["trip"] == "night"
    assert res[0]["depart"] == iso(0, 30) and res[0]["arrive"] == iso(0, 40)
    assert [rides(it)[0]["trip"] for it in res] == ["night", "morning", "night_mon"]
    assert res[2]["depart"] == iso(0, 50, day=(2026, 11, 17))


def test_map_point_origin_walks_to_the_stop(tmp_path):
    stops = {"A": (0, 0, "1"), "B": (5000, 0, "2"), "F": (-3000, 0, "9")}
    p = _write(tmp_path, stops, {"1": {"0": ["A", "B"]}, "9": {"0": ["F", "B"]}}, [
        ("t1", "1", "0", "work", [hms(8, 5), hms(8, 15)]),
        ("far", "9", "0", "work", [hms(8, 0), hms(8, 5)]),  # 2.75 km away: out of reach
    ])
    lon, lat = ll(-250, 0)
    res = p.plan({"lat": lat, "lon": lon}, {"station": "2"}, at(8, 0))
    best = res[0]
    assert [leg["kind"] for leg in best["legs"]] == ["walk", "ride"]
    walk = best["legs"][0]
    # 250 m × 1.3 / 1.25 m/s = 260 s, leaving just in time for the 8:05 departure.
    assert walk["start"] == iso(8, 0, 40) and walk["end"] == iso(8, 5)
    assert walk["m"] == 325 and best["walkM"] == 325
    assert walk["from"]["stop"] is None and walk["to"]["stop"] == "A"
    assert walk["coords"][0] == [lon, lat]
    assert best["depart"] == iso(8, 0, 40) and best["arrive"] == iso(8, 15)
    assert all("far" not in [r["trip"] for r in rides(it)] for it in res)
    # Close to the stop, walking all the way wins over waiting for the bus.
    lon2, lat2 = ll(300, 0)
    res = p.plan({"lat": lat, "lon": lon}, {"lat": lat2, "lon": lon2}, at(8, 0))
    assert [leg["kind"] for leg in res[0]["legs"]] == ["walk"] and res[0]["transfers"] == 0
