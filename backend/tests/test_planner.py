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


def test_same_place_plans_nothing(tmp_path):
    # Q is a second platform of station 1: line 2 would bring you back to where you started.
    stops = {"A": (0, 0, "1"), "B": (5000, 0, "2"), "Q": (0, 20, "1")}
    p = _write(tmp_path, stops, {"1": {"0": ["A", "B"]}, "2": {"0": ["B", "Q"]}}, [
        ("out", "1", "0", "work", [hms(8, 0), hms(8, 10)]),
        ("back", "2", "0", "work", [hms(8, 15), hms(8, 25)]),
    ])
    assert p.plan_with_reason({"station": "1"}, {"station": "1"}, at(7, 55)) == ([], "same_place")
    (lon, lat), (lon2, lat2) = ll(2000, 0), ll(2010, 0)
    assert p.plan_with_reason({"lat": lat, "lon": lon}, {"lat": lat2, "lon": lon2}, at(7, 55)) == ([], "same_place")


def test_reasons_for_no_options(tmp_path):
    stops = {"A": (0, 0, "1"), "B": (5000, 0, "2")}
    p = _write(tmp_path, stops, {"1": {"0": ["B", "A"]}}, [("t", "1", "0", "work", [hms(8, 0), hms(8, 10)])])
    lon, lat = ll(0, 5000)  # 5 km from any stop
    assert p.plan_with_reason({"lat": lat, "lon": lon}, {"station": "2"}, at(7, 55)) == ([], "no_stops_near_origin")
    assert p.plan_with_reason({"station": "2"}, {"lat": lat, "lon": lon}, at(7, 55)) == ([], "no_stops_near_destination")
    assert p.plan_with_reason({"station": "1"}, {"station": "2"}, at(7, 55)) == ([], "no_connection")
    assert p.plan_with_reason({"station": "2"}, {"station": "1"}, at(7, 55))[1] is None


def test_later_one_transfer_option_is_kept(tmp_path):
    stops = {"A": (0, 0, "1"), "B": (5000, 0, "2"), "C": (10_000, 0, "3")}
    p = _write(tmp_path, stops, {"1": {"0": ["A", "C"]}, "2": {"0": ["A", "B"]}, "3": {"0": ["B", "C"]}}, [
        ("direct", "1", "0", "work", [hms(8, 0), hms(8, 41)]),
        ("first", "2", "0", "work", [hms(8, 20), hms(8, 30)]),
        ("second", "3", "0", "work", [hms(8, 32), hms(8, 40)]),
    ])
    res = p.plan({"station": "1"}, {"station": "3"}, at(7, 55))
    # The transfer saves only a minute, but leaves 20 minutes later.
    assert [[r["trip"] for r in rides(it)] for it in res] == [["first", "second"], ["direct"]]


def test_later_departures_just_after_the_best_are_found(tmp_path):
    stops = {"A": (0, 0, "1"), "B": (5000, 0, "2")}
    p = _write(tmp_path, stops, {"1": {"0": ["A", "B"]}}, [
        ("t1", "1", "0", "work", [hms(8, 0), hms(8, 10)]),
        ("t2", "1", "0", "work", [hms(8, 0, 30), hms(8, 12)]),
        ("t3", "1", "0", "work", [hms(8, 20), hms(8, 30)]),
    ])
    res = p.plan({"station": "1"}, {"station": "2"}, at(7, 59))
    assert [rides(it)[0]["trip"] for it in res] == ["t1", "t2", "t3"]


def test_late_evening_finds_the_next_days_first_trips(tmp_path):
    stops = {"A": (0, 0, "1"), "B": (5000, 0, "2")}
    p = _write(tmp_path, stops, {"1": {"0": ["A", "B"]}}, [("t", "1", "0", "work", [hms(8, 0), hms(8, 10)])])
    res, reason = p.plan_with_reason({"station": "1"}, {"station": "2"}, at(23, 30))
    assert reason is None and res[0]["depart"] == iso(8, 0, day=(2026, 11, 17))


def test_short_walk_is_offered_next_to_rides_and_replaces_slower_ones(tmp_path):
    # 900 m apart: the walk is 1170 m, 936 s (15:36).
    stops = {"A": (0, 0, "1"), "B": (900, 0, "2")}
    p = _write(tmp_path, stops, {"1": {"0": ["A", "B"]}}, [
        ("t1", "1", "0", "work", [hms(8, 8), hms(8, 12)]),
        ("slow", "1", "0", "work", [hms(8, 30), hms(8, 50)]),  # 20 min: slower than walking
        ("t3", "1", "0", "work", [hms(8, 45), hms(8, 55)]),
    ])
    (lon, lat), (lon2, lat2) = ll(0), ll(900)
    res = p.plan({"lat": lat, "lon": lon}, {"lat": lat2, "lon": lon2}, at(8, 0))
    kinds = [[r["trip"] for r in rides(it)] or "walk" for it in res]
    assert kinds == [["t1"], "walk", ["t3"]]
    assert res[1]["arrive"] == iso(8, 15, 36) and res[1]["walkM"] == 1170


def test_ride_geometry_falls_back_per_hop(tmp_path):
    # B → C is 100 m apart but the shape loops 3 km north between them; X lies 400 m off the shape.
    stops = {"A": (0, 0, "1"), "B": (1000, 0, "2"), "C": (1100, 0, "3"), "D": (2100, 0, "4"), "X": (2600, 400, "5")}
    bend1, bend2 = list(ll(500, 100)), list(ll(1600, 100))
    shape = [list(ll(0)), bend1, list(ll(1000)), list(ll(1000, 1500)), list(ll(1100, 1500)), list(ll(1100)),
             bend2, list(ll(2100)), list(ll(2600))]
    p = _write(tmp_path, stops, {"1": {"0": ["A", "B", "C", "D", "X"]}},
               [("t", "1", "0", "work", [hms(8, 0), hms(8, 2), hms(8, 3), hms(8, 5), hms(8, 6)])],
               shapes={"1": {"0": shape}})
    coords = rides(p.plan({"station": "1"}, {"station": "5"}, at(7, 55))[0])[0]["coords"]
    r = lambda c: [round(c[0], 6), round(c[1], 6)]  # noqa: E731
    assert r(bend1) in coords and r(bend2) in coords
    assert r(ll(1000, 1500)) not in coords  # the loop is drawn straight
    assert coords[-1] == r(ll(2600, 400)) and coords[-2] == r(ll(2100))  # D → X straight


def test_api_plan_takes_a_naive_time_as_bratislava_and_gives_a_reason(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import mhd.app
    from mhd.poller import Poller

    stops = {"A": (0, 0, "1"), "B": (5000, 0, "2")}
    _write(tmp_path, stops, {"1": {"0": ["A", "B"]}}, [("t", "1", "0", "work", [hms(8, 0), hms(8, 10)])])
    d = tmp_path / "static"
    lines = json.loads((d / "lines.json").read_text())  # what Static needs besides the planner's fields
    lines["1"]["directions"]["0"].update(headsigns=["End"], stopDist=[0, 5000], length=5000)
    (d / "lines.json").write_text(json.dumps(lines))
    (d / "meta.json").write_text(json.dumps({"feedVersion": "t"}))
    monkeypatch.setattr(mhd.app, "DATA_DIR", tmp_path)
    with TestClient(mhd.app.create_app(poller=Poller(logger=None), start_polling=False)) as c:
        r = c.get("/api/plan", params={"from": "1", "to": "2", "at": "2026-11-16T07:55"})
        assert r.status_code == 200
        body = r.json()
        assert body["options"][0]["depart"] == iso(8, 0) and body["reason"] is None
        assert body["live"] is False  # a past time doesn't get today's delays
        assert c.get("/api/plan", params={"from": "1", "to": "1"}).json() == {
            "options": [], "reason": "same_place", "live": True}
