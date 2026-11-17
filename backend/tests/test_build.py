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


def _zip(tables: dict[str, list[dict]]) -> bytes:
    import csv
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, rows in tables.items():
            s = io.StringIO()
            w = csv.DictWriter(s, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
            z.writestr(f"{name}.txt", s.getvalue())
    return buf.getvalue()


def _regional_zip() -> bytes:
    """Line 512 Pezinok → Viničné → Senec along a zigzag road (6.8 km; the stops are 6 km apart in
    a straight line). Like IDS BK's feed: no direction_id, trip numbers odd one way and even the
    other, two platforms named alike. It also has a line 69, which is DPB's number."""
    def pt(x, y):
        lon, lat = to_lonlat(BX + x, BY + y)
        return str(lon), str(lat)

    stops = [{"stop_id": sid, "stop_name": name, "stop_lon": pt(x, 0)[0], "stop_lat": pt(x, 0)[1], "platform_code": plat}
             for sid, name, x, plat in [("100", "Pezinok, aut. st.", 0, "A"), ("101", "Pezinok, aut. st. ", 30, "B"),
                                        ("200", "Viničné", 3000, ""), ("300", "Senec", 6000, "")]]
    zig = [(0, 0), (1500, 800), (3000, 0), (4500, 800), (6000, 0)]
    shapes = [{"shape_id": sid, "shape_pt_lon": pt(x, y)[0], "shape_pt_lat": pt(x, y)[1], "shape_pt_sequence": str(i)}
              for sid, pts in [("s0", zig), ("s1", zig[::-1])] for i, (x, y) in enumerate(pts)]
    trips, stop_times = [], []
    for tid, route, no, head, shape, pattern, hour in [
        ("t1", "R1", "1", "Senec", "s0", ["100", "200", "300"], 7),
        ("t3", "R1", "3", "Senec", "s0", ["100", "200", "300"], 8),
        ("t2", "R1", "2", "Pezinok", "s1", ["300", "200", "101"], 9),
        ("t5", "R2", "1", "Senec", "s0", ["100", "300"], 10),
    ]:
        trips.append({"route_id": route, "service_id": "wd", "trip_id": tid, "trip_headsign": head,
                      "trip_short_name": no, "direction_id": "", "shape_id": shape})
        for i, s in enumerate(pattern):
            t = f"{hour:02d}:{10 * i:02d}:00"
            along = {"100": 0, "101": 34, "200": 3400, "300": 6800}[s]  # metres along s0
            stop_times.append({"trip_id": tid, "arrival_time": t, "departure_time": t, "stop_id": s, "stop_sequence": str(i + 1),
                               "shape_dist_traveled": str(along if shape == "s0" else 6800 - along)})
    return _zip({
        "agency": [{"agency_id": "A1", "agency_name": "ARRIVA"}],
        "routes": [{"route_id": r, "agency_id": "A1", "route_short_name": n, "route_type": "3", "route_color": "", "route_text_color": ""}
                   for r, n in [("R1", "512"), ("R2", "69")]],
        "trips": trips,
        "stops": stops,
        "stop_times": stop_times,
        "shapes": shapes,
        "calendar": [{"service_id": "wd", "monday": "1", "tuesday": "1", "wednesday": "1", "thursday": "1", "friday": "1",
                      "saturday": "0", "sunday": "0", "start_date": "20261101", "end_date": "20261213"}],
    })


def test_regional_feed_joins_the_build_and_stays_out_of_the_planner(tmp_path):
    from mhd.planner import Planner

    out = build.build(_gtfs(), {"elements": []})
    build.build_regional(_regional_zip(), out)

    line = out["lines"]["512"]
    assert line["regional"] is True and line["operator"] == "ARRIVA"
    dirs = line["directions"]
    assert {d: (di["headsign"], di["stops"]) for d, di in dirs.items()} == {
        "0": ("Senec", ["idsbk:100", "idsbk:200", "idsbk:300"]),
        "1": ("Pezinok", ["idsbk:300", "idsbk:200", "idsbk:101"]),
    }
    # Drawn along the feed's road, not straight from stop to stop.
    assert abs(dirs["0"]["length"] - 6800) < 30 and abs(dirs["0"]["stopDist"][1] - 3400) < 30
    assert out["stations"]["idsbk:100"]["name"] == "Pezinok, aut. st."
    assert sorted(out["stations"]["idsbk:100"]["stops"]) == ["idsbk:100", "idsbk:101"]
    regional_trips = {t["id"]: t["no"] for t in out["timetable"]["trips"] if t["id"].startswith("idsbk:")}
    assert regional_trips == {"idsbk:t1": "1", "idsbk:t3": "3", "idsbk:t2": "2"}
    # DPB's line 69 is untouched: the regional line with its number is left out.
    assert "regional" not in out["lines"]["69"] and not any(s.startswith("idsbk:") for s in out["lines"]["69"]["directions"]["0"]["stops"])
    assert out["meta"]["regional"]["feedEnd"] == "20261213"

    build.write(out, tmp_path / "static")
    p = Planner(tmp_path / "static")
    assert p.stop_ids and not [s for s in p.stop_ids if s.startswith("idsbk:")]
    assert not [c for c in p.stations if c.startswith("idsbk:")]
    assert {p.pat_line[p.trip_pat[t[0]]] for t in p.trips} == {"69"}
