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


def _feed(line, xy, trips_spec):
    """A one-route feed: stops at metre offsets `xy`, trips as (id, direction, headsign, stops, start s)."""
    stops = []
    for sid, (x, y) in xy.items():
        lon, lat = to_lonlat(BX + x, BY + y)
        stops.append({"stop_id": sid, "stop_name": sid, "stop_code": "", "platform_code": "", "stop_lon": str(lon), "stop_lat": str(lat)})
    trips, stop_times = [], []
    for tid, direction, headsign, pattern, start in trips_spec:
        trips.append({"route_id": "r", "trip_id": tid, "direction_id": direction, "trip_headsign": headsign, "service_id": "wd"})
        for i, s in enumerate(pattern):
            t = start + 120 * i
            hms = f"{t // 3600:02d}:{t // 60 % 60:02d}:{t % 60:02d}"
            stop_times.append({"trip_id": tid, "stop_sequence": str(i + 1), "stop_id": s, "departure_time": hms, "arrival_time": hms})
    return {
        "feed_info": [],
        "routes": [{"route_id": "r", "route_short_name": line, "route_type": "0", "route_color": "", "route_text_color": ""}],
        "trips": trips,
        "stops": stops,
        "stop_times": stop_times,
        "calendar": [],
        "calendar_dates": [],
    }


def test_branch_with_the_same_headsign_is_one_direction_with_a_branch_shape():
    # Like line 4 to Pri kríži: trams from Z every 10 min and from the N terminal, 900 m off the
    # main route, in between. Both run B → C → P, so the trunk sees a tram every 5 min.
    xy = {"Z": (0, 0), "A": (600, 0), "B": (1200, 0), "C": (1800, 0), "P": (2400, 0), "N": (600, 900)}
    spec = []
    for k in range(6):
        spec.append((f"z{k}", "1", "P", "ZABCP", 7 * 3600 + 600 * k))
        spec.append((f"n{k}", "1", "P", "NBCP", 7 * 3600 + 420 + 600 * k))
    spec.append(("a0", "1", "P", "ABCP", 8 * 3600))  # starts partway along
    out = build.build(_feed("4", xy, spec), {"elements": []})
    dirs = out["lines"]["4"]["directions"]
    assert list(dirs) == ["1"]
    assert dirs["1"]["stops"] == list("ZABCP") and dirs["1"]["headsigns"] == ["P"]
    assert list(out["shapes"]["4"]) == ["1"]
    (branch,) = out["branches"]["4"]["1"]
    assert len(branch) >= 2 and to_xy(*branch[0])[1] - BY > 800  # starts at N
    # Every trip is timed at B, the first stop all of them serve: one tram every 5 minutes.
    assert dirs["1"]["refStop"] == 2
    deps = out["service"]["departures"]["4"]["1"]["wd"]
    assert len(deps) == 13
    assert deps[:4] == [7 * 3600 + 240, 7 * 3600 + 540, 7 * 3600 + 840, 7 * 3600 + 1140]
    assert 8 * 3600 + 120 in deps  # the trip from A, at B two minutes later


def test_two_stop_direction_survives():
    # Like line 144: Koliba → Zochova chata → Kamzík up, and straight back Kamzík → Koliba.
    xy = {"K": (0, 0), "Z": (500, 400), "M": (900, 900)}
    spec = [(f"u{k}", "0", "M", "KZM", 9 * 3600 + 1800 * k) for k in range(3)]
    spec += [(f"d{k}", "1", "K", "MK", 9 * 3600 + 900 + 1800 * k) for k in range(3)]
    spec += [("stub", "1", "K", "KK", 12 * 3600)]
    out = build.build(_feed("144", xy, spec), {"elements": []})
    dirs = out["lines"]["144"]["directions"]
    assert {d: di["stops"] for d, di in dirs.items()} == {"0": ["K", "Z", "M"], "1": ["M", "K"]}
    assert dirs["1"]["length"] > 1000
    assert out["service"]["departures"]["144"]["1"]["wd"] == [9 * 3600 + 900 + 1800 * k for k in range(3)]
