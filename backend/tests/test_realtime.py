import json
from datetime import datetime, timedelta

from mhd import derive, lineview
from mhd.feed import Vehicle
from mhd.geo import to_lonlat, to_xy
from mhd.poller import Poller
from mhd.static import TZ, Static

BASE = to_xy(17.10, 48.15)
MON_1630 = datetime(2026, 11, 16, 16, 30, tzinfo=TZ)
H16 = 16 * 3600


def ll(x, y=0.0):
    return to_lonlat(BASE[0] + x, BASE[1] + y)


def _static(tmp_path):
    """Line 83 runs 10 km due east, A (0 m) → M (5 km) → B (10 km) in 20 min, every 10 min from 16:00."""
    d = tmp_path / "static"
    d.mkdir()
    stops = {
        s: {"name": n, "code": s, "platform": "1", "lat": ll(x)[1], "lon": ll(x)[0], "lines": ["83"], "station": s}
        for s, n, x in [("A", "Západ", 0), ("M", "Stred", 5000), ("B", "Východ", 10_000)]
    }
    lines = {"83": {"line": "83", "type": "bus", "color": "#000", "textColor": "#fff", "directions": {
        "0": {"headsign": "Východ", "headsigns": ["Východ"], "from": "Západ", "stops": ["A", "M", "B"],
              "stopDist": [0, 5000, 10_000], "length": 10_000, "duration": 1200},
    }}}
    service = {"calendar": {"work": {"days": [1, 1, 1, 1, 1, 0, 0], "start": "20261101", "end": "20271231",
                                     "added": [], "removed": []}},
               "departures": {"83": {"0": {"work": [H16 + i * 600 for i in range(12)]}}}}
    timetable = {
        "patterns": [{"line": "83", "dir": "0", "stops": ["A", "M", "B"]}],
        "trips": [{"id": f"t{16 * 60 + i * 10}", "p": 0, "svc": "work", "head": "Východ",
                   "t": [H16 + i * 600, H16 + i * 600 + 600, H16 + i * 600 + 1200]} for i in range(12)],
    }
    files = {"meta": {"feedVersion": "t"}, "lines": lines, "stops": stops, "service": service,
             "shapes": {"83": {"0": [list(ll(0)), list(ll(10_000))]}}, "timetable": timetable}
    for name, obj in files.items():
        (d / f"{name}.json").write_text(json.dumps(obj))
    return Static.load(tmp_path)


def _bus(key, x, delay, dest="Východ", y=3.0):
    lon, lat = ll(x, y)
    return Vehicle(key, "83", dest, "bus", lat, lon, delay, 1, 90)


# Trip t960 leaves A at 16:00, t980 at 16:20, t990 at 16:30. At 16:30 (12 s per 100 m):
VEHICLES = [
    _bus("known", 4000, 120),  # 16:20 trip is due at 4 km at 16:28, two minutes ago
    _bus("capped", 7000, 900),  # "15+ min": the 16:00 trip was due at 7 km at 16:14
    _bus("nodelay", 600, None),  # the 16:30 trip is due at 600 m at 16:31
    _bus("depot", 3000, 900, dest="Depo Petržalka"),
    _bus("parked", 5000, 900, y=800),  # 800 m beside the route
]


def _derive(tmp_path):
    s = _static(tmp_path)
    p = Poller(logger=None)
    p.apply(VEHICLES, MON_1630)
    return s, p.snapshot, lineview.derive_poll(p.snapshot, s, MON_1630)


def test_vehicles_are_assigned_to_the_trips_they_run(tmp_path):
    _, _, derived = _derive(tmp_path)
    rt = derived.realtime
    assert rt.trip_vehicle() == {"t980": "known", "t960": "capped", "t990": "nodelay"}
    # Only a known, uncapped delay is reported to the planner.
    assert rt.trip_delays() == {"t980": 120}


def test_service_state_and_band(tmp_path):
    _, snap, derived = _derive(tmp_path)
    service = {v.key: derived.service(v.key) for v in snap.vehicles}
    assert service == {"known": "running", "capped": "running", "nodelay": "running",
                       "depot": "depot", "parked": "parked"}
    bands = {v.key: derive.vehicle_json(v, snap, MON_1630, service[v.key])["band"] for v in snap.vehicles}
    assert bands == {"known": 1, "capped": 3, "nodelay": None, "depot": None, "parked": None}
    st = lineview.city_status(snap, derived, None, MON_1630)
    # The depot and parked buses' 15+ min delays don't make the city late.
    assert st["vehicles"] == 3 and st["withDelay"] == 2 and st["shareLate"] == 0.5


def test_departure_board_applies_delay_only_before_the_stop(tmp_path):
    _, _, derived = _derive(tmp_path)
    rt = derived.realtime
    # At M (5 km): the 16:20 trip's bus is 1 km before it, two minutes late. The 16:00 trip's
    # bus has passed M, so it isn't listed although it is late.
    board = rt.departures(["M"], MON_1630, horizon_s=20 * 60)
    got = [(d["trip"], d["scheduled"][11:16], d["predicted"] and d["predicted"][11:16], d["live"], d["minutes"])
           for d in board]
    assert got == [
        ("t980", "16:30", "16:32", True, 2),
        ("t990", "16:40", "16:40", True, 10),
        ("t1000", "16:50", None, False, 20),
    ]
    assert board[0]["vehicle"] == "known" and board[0]["stopId"] == "M" and board[0]["platform"] == "1"
    # The 16:20 bus has passed A; the next departure there is the 16:30 bus already on its way.
    assert "t980" not in [d["trip"] for d in rt.departures(["A"], MON_1630)]
    # B is the last stop: arrivals only.
    assert rt.departures(["B"], MON_1630) == []


def test_vehicle_trip_lists_remaining_stops(tmp_path):
    _, _, derived = _derive(tmp_path)
    trip = derived.realtime.vehicle_trip("capped", MON_1630)
    assert trip["id"] == "t960" and trip["uncertain"] is True
    # Only B is left; the capped delay is at least 15 min, here 16 min from its position.
    assert [(s["stopId"], s["scheduled"][11:16], s["predicted"][11:16], s["arrival"]) for s in trip["stops"]] == [
        ("B", "16:20", "16:36", True)
    ]
    assert derived.realtime.vehicle_trip("parked", MON_1630) is None


def test_bus_waiting_at_the_first_stop_takes_the_next_departure(tmp_path):
    s = _static(tmp_path)
    p = Poller(logger=None)
    # 16:32: the 16:30 bus is on its way, 1 km out; the next one waits for 16:40.
    p.apply([_bus("w", 30, 0), _bus("r", 1000, 0)], MON_1630 + timedelta(minutes=2))
    derived = lineview.derive_poll(p.snapshot, s, MON_1630 + timedelta(minutes=2))
    assert derived.realtime.trip_vehicle() == {"t990": "r", "t1000": "w"}
    assert derived.service("w") == "layover" and derived.service("r") == "running"
    trip = derived.realtime.vehicle_trip("w", MON_1630 + timedelta(minutes=2))
    assert trip["waiting"] and trip["stops"][0]["predicted"][11:16] == "16:40"


def test_vehicle_fitting_no_trip_runs_only_with_a_known_delay_while_its_line_runs(tmp_path):
    s = _static(tmp_path)
    p = Poller(logger=None)
    # "bunched" follows "known" on the 16:20 trip (the 16:10 trip is too early for it and the 16:30
    # trip is "nodelay"'s); "yard" reports a capped delay where the capped 16:00 bus already runs.
    p.apply(VEHICLES + [_bus("bunched", 4050, 60), _bus("yard", 7050, 900)], MON_1630)
    derived = lineview.derive_poll(p.snapshot, s, MON_1630)
    rt = derived.realtime
    assert rt.trip_id("bunched") is None and derived.service("bunched") == "running"
    # One of the two capped buses takes the 16:00 trip; the other fits none and isn't running.
    spare = [k for k in ("capped", "yard") if rt.trip_id(k) is None]
    assert len(spare) == 1 and derived.service(spare[0]) == "unknown"
    # After the line's last trip (17:50 → 18:10) nothing on the route runs.
    late = MON_1630 + timedelta(hours=2, minutes=30)
    p = Poller(logger=None)
    p.apply([_bus("after", 5000, 60)], late)
    assert lineview.derive_poll(p.snapshot, s, late).service("after") == "unknown"


def test_board_keeps_a_trip_scheduled_over_an_hour_ago_while_its_vehicle_runs(tmp_path):
    from mhd.realtime import Assignment

    s, _, derived = _derive(tmp_path)
    rt = derived.realtime
    now = MON_1630 + timedelta(hours=1, minutes=10)  # the 16:00 trip was due at M at 16:10
    ti = s.timetable.by_id["t960"]
    rt.assigned = {"capped": Assignment(trip=ti, offset=0, along=4000, next_stop=1, delay=3900,
                                        uncertain=True, waiting=False)}
    board = rt.departures(["M"], now, horizon_s=20 * 60)
    assert ("t960", "17:40") in [(d["trip"], d["predicted"][11:16]) for d in board if d["live"]]
