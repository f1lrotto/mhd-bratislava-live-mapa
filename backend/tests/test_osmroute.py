from mhd import osmroute
from mhd.geo import Polyline, to_lonlat

# A 400 m × 400 m block. The line's relation runs clockwise around it:
#   1 (0,400) ──▶ 2 (400,400)
#   ▲                 │
#   │                 ▼
#   4 (0,0)   ◀── 3 (400,0)
# A second, two-way street from another relation joins 1 and 3 diagonally (cost ×1.5).
XY = {1: (0, 400), 2: (400, 400), 3: (400, 0), 4: (0, 0)}
BASE = (17.10, 48.15)


def _node_geom(n):
    from mhd.geo import to_xy

    bx, by = to_xy(*BASE)
    lon, lat = to_lonlat(bx + XY[n][0], by + XY[n][1])
    return {"lon": lon, "lat": lat}


def _way(wid, nodes, tags=None):
    return {"type": "way", "id": wid, "nodes": nodes, "geometry": [_node_geom(n) for n in nodes], "tags": tags or {}}


def _lonlat(x, y):
    from mhd.geo import to_xy

    bx, by = to_xy(*BASE)
    return to_lonlat(bx + x, by + y)


def _elements():
    # Ways 11 and 13 are stored against the travel direction, so the relation's order decides.
    ways = [_way(10, [1, 2]), _way(11, [3, 2]), _way(12, [3, 4]), _way(13, [1, 4]), _way(20, [1, 3])]
    own = {
        "type": "relation", "id": 100, "tags": {"route": "bus", "ref": "83"},
        "members": [{"type": "way", "ref": w, "role": ""} for w in (10, 11, 12, 13)],
    }
    other = {
        "type": "relation", "id": 200, "tags": {"route": "trolleybus", "ref": "40"},
        "members": [{"type": "way", "ref": 20, "role": ""}],
    }
    return ways + [own, other]


def test_relation_way_directions_follow_member_order():
    ways = {e["id"]: e for e in _elements() if e["type"] == "way"}
    dirs = osmroute.relation_way_directions([(ways[w], "") for w in (10, 11, 12, 13)])
    assert dirs == [1, -1, 1, -1]


def test_route_follows_relation_direction_not_shortest_reverse():
    g = osmroute.build_graph(_elements(), "83", "bus")
    # From the middle of the top edge to the middle of the left edge. Going straight back west
    # and down is 400 m but against the relation; the route must go clockwise (or use the
    # diagonal shortcut from another line), never backwards along 2→1.
    coords, stop_dist, fallbacks = osmroute.route_stops(g, [_lonlat(200, 400), _lonlat(0, 200)])
    assert fallbacks == 0
    length = stop_dist[-1]
    assert length > 700, length
    # It passes the east side of the block: some point has x ≈ 400 m.
    xs = [Polyline([c]).xy[0][0] - Polyline([BASE]).xy[0][0] for c in coords]
    assert max(xs) > 390


def test_tram_does_not_use_road_relations():
    g = osmroute.build_graph(_elements(), "4", "tram")
    coords, _, fallbacks = osmroute.route_stops(g, [_lonlat(200, 400), _lonlat(0, 200)])
    assert fallbacks == 1 and len(coords) == 2


def test_polyline_project_and_bearing():
    p = Polyline([_lonlat(0, 0), _lonlat(1000, 0), _lonlat(1000, 1000)])
    along, off = p.project(*_lonlat(1010, 500))
    assert abs(along - 1500) < 1 and abs(off - 10) < 1
    assert p.bearing_at(200) == 90 and p.bearing_at(1200) == 0
