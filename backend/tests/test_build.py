from mhd import build
from mhd.geo import to_lonlat, to_xy

BX, BY = to_xy(17.10, 48.15)
# A 600 m square served as a loop, like line 69: A → B → C, then C → D → A.
XY = {"A": (0, 0), "B": (600, 0), "C": (600, 600), "D": (0, 600)}


def _gtfs():
    stops = []
    for sid, (x, y) in XY.items():
        lon, lat = to_lonlat(BX + x, BY + y)
        stops.append({"stop_id": sid, "stop_name": sid, "stop_code": "", "platform_code": "", "stop_lon": str(lon), "stop_lat": str(lat)})
    trips, stop_times = [], []

    def trip(tid, direction, headsign, pattern, start_min):
        trips.append({"route_id": "r", "trip_id": tid, "direction_id": direction, "trip_headsign": headsign, "service_id": "wd"})
        for i, s in enumerate(pattern):
            t = f"07:{start_min + 2 * i:02d}:00"
            stop_times.append({"trip_id": tid, "stop_sequence": str(i + 1), "stop_id": s, "departure_time": t, "arrival_time": t})

    # DPB puts both legs in direction 0 and a depot stub in direction 1.
    for k in range(2):
        trip(f"out{k}", "0", "C", "ABC", 30 * k)
        trip(f"back{k}", "0", "A", "CDA", 30 * k + 5)
        trip(f"stub{k}", "1", "A", "AA", 30 * k + 12)
    return {
        "feed_info": [],
        "routes": [{"route_id": "r", "route_short_name": "69", "route_type": "3", "route_color": "", "route_text_color": ""}],
        "trips": trips,
        "stops": stops,
        "stop_times": stop_times,
        "calendar": [],
        "calendar_dates": [],
    }


def test_loop_legs_become_directions_and_stubs_are_dropped():
    out = build.build(_gtfs(), {"elements": []})
    dirs = out["lines"]["69"]["directions"]
    assert {d: (di["stops"], di["headsigns"]) for d, di in dirs.items()} == {
        "0": (["A", "B", "C"], ["C"]),
        "0-2": (["C", "D", "A"], ["A"]),
    }
    assert dirs["0"]["length"] > 1000 and set(out["shapes"]["69"]) == {"0", "0-2"}
    # Each direction's departures come from its own origin only: one 30-minute stream each.
    deps = out["service"]["departures"]["69"]
    assert deps["0"]["wd"] == [7 * 3600, 7 * 3600 + 1800]
    assert deps["0-2"]["wd"] == [7 * 3600 + 300, 7 * 3600 + 2100]
