"""Street-following route geometry from OpenStreetMap public transport relations.

GTFS shapes from DPB are straight lines between stops. To draw a line along the streets, each pair
of consecutive stops is routed over a directed graph built from OSM route relations:

* Ways in the relations of the same line and mode, in the direction the relation travels them,
  cost their length.
* Where consecutive ways of the line's relation don't touch (a mapping hole) and are at most
  150 m apart, a straight edge joins them.
* If the line has no relation running this direction, its other relations' ways can also be
  travelled backwards, where oneway tags allow, at 1.2× their length.
* Ways in any relation of the same mode group (road: bus + trolleybus, rail: tram) cost 1.5× their
  length and respect oneway tags (with bus/psv exceptions). This bridges gaps in a line's relation.
* If no path exists, or it is more than twice the straight distance plus 600 m, the pair is joined
  by a straight segment and counted as a fallback.
"""

from __future__ import annotations

import heapq
import math
from collections import defaultdict
from dataclasses import dataclass, field

from .geo import project_on_segment, to_lonlat, to_xy

ROLE_ROUTE = {"", "forward", "backward", "route"}
MODE_GROUP = {"bus": "road", "trolleybus": "road", "tram": "rail"}
OTHER_LINE_FACTOR = 1.5
REVERSE_OWN_FACTOR = 1.2
GAP_MAX_M = 150.0  # bridge holes between consecutive relation members up to this long
SNAP_RADIUS_M = 60.0
SNAP_MAX_M = 200.0
SNAP_PENALTY = 3.0  # cost per metre of distance between a stop and where it snaps


def _oneway(tags: dict) -> int:
    """1 = way order only, -1 = reverse only, 0 = both directions, for buses."""
    for k in ("oneway:bus", "oneway:psv", "oneway:trolleybus"):
        if tags.get(k) == "no":
            return 0
    if tags.get("busway") == "opposite_lane" or tags.get("busway:left") == "opposite_lane":
        return 0
    v = tags.get("oneway")
    if v in ("yes", "1", "true"):
        return 1
    if v == "-1":
        return -1
    if tags.get("junction") in ("roundabout", "circular") and v != "no":
        return 1
    return 0


def relation_way_directions(member_ways: list[tuple[dict, str]]) -> list[int]:
    """For each (way, role) in relation order, the direction it is travelled: 1, -1, or 0 (unknown)."""
    dirs: list[int] = []
    n = len(member_ways)
    exit_node: int | None = None
    for i, (w, role) in enumerate(member_ways):
        nodes = w["nodes"]
        first, last = nodes[0], nodes[-1]
        d = 0
        if first == last:  # closed way, e.g. a roundabout: travelled in node order
            d = 1
            nxt = member_ways[i + 1][0]["nodes"] if i + 1 < n else None
            exit_node = next((x for x in nodes if nxt and x in (nxt[0], nxt[-1])), None)
            dirs.append(d)
            continue
        if exit_node is not None:
            if first == exit_node:
                d = 1
            elif last == exit_node:
                d = -1
        if d == 0 and i + 1 < n:
            nn = member_ways[i + 1][0]["nodes"]
            nxt_ends = (nn[0], nn[-1]) if nn[0] != nn[-1] else tuple(nn)
            if last in nxt_ends:
                d = 1
            elif first in nxt_ends:
                d = -1
        if d == 0:
            d = {"forward": 1, "backward": -1}.get(role, 0)
        dirs.append(d)
        exit_node = last if d == 1 else first if d == -1 else None
    return dirs


@dataclass
class Graph:
    coords: dict[int, tuple[float, float]] = field(default_factory=dict)  # node -> (x, y) metres
    # node -> {neighbour: cost}
    adj: dict[int, dict[int, float]] = field(default_factory=lambda: defaultdict(dict))
    # spatial grid of directed edges for snapping
    grid: dict[tuple[int, int], set[tuple[int, int]]] = field(default_factory=lambda: defaultdict(set))
    cell: float = 100.0

    def add_edge(self, a: int, b: int, factor: float) -> None:
        if a == b:
            return
        (ax, ay), (bx, by) = self.coords[a], self.coords[b]
        cost = math.hypot(bx - ax, by - ay) * factor
        if cost < self.adj[a].get(b, math.inf):
            self.adj[a][b] = cost
        c = self.cell
        for gx in range(int(min(ax, bx) // c), int(max(ax, bx) // c) + 1):
            for gy in range(int(min(ay, by) // c), int(max(ay, by) // c) + 1):
                self.grid[(gx, gy)].add((a, b))

    def snap(self, x: float, y: float) -> list[tuple[int, int, float, float, float, float]]:
        """Candidate edges near a point: (a, b, t, dist, qx, qy)."""
        out = []
        for radius in (SNAP_RADIUS_M, SNAP_MAX_M):
            c = self.cell
            r = int(radius // c) + 1
            gx0, gy0 = int(x // c), int(y // c)
            seen: set[tuple[int, int]] = set()
            for gx in range(gx0 - r, gx0 + r + 1):
                for gy in range(gy0 - r, gy0 + r + 1):
                    seen |= self.grid.get((gx, gy), set())
            for a, b in seen:
                (ax, ay), (bx, by) = self.coords[a], self.coords[b]
                t, d, qx, qy = project_on_segment(x, y, ax, ay, bx, by)
                if d <= radius:
                    out.append((a, b, t, d, qx, qy))
            if out:
                break
        out.sort(key=lambda c: c[3])
        return out[:12]


def _route_members(rel: dict, ways: dict) -> list[tuple[dict, str]]:
    return [
        (ways[m["ref"]], m.get("role", ""))
        for m in rel.get("members", [])
        if m["type"] == "way" and m.get("role", "") in ROLE_ROUTE and m["ref"] in ways
    ]


def build_graph(osm_elements: list[dict], line: str, mode: str, reverse_own: bool = False) -> Graph:
    """The routing graph for one line. With reverse_own, the line's own relations can also be
    travelled backwards (for a direction that has no relation of its own)."""
    group = MODE_GROUP[mode]
    ways = {e["id"]: e for e in osm_elements if e["type"] == "way" and "geometry" in e}
    g = Graph()
    for w in ways.values():
        for nid, pt in zip(w["nodes"], w["geometry"]):
            if pt:
                g.coords[nid] = to_xy(pt["lon"], pt["lat"])
    for rel in osm_elements:
        if rel["type"] != "relation":
            continue
        rmode = rel.get("tags", {}).get("route")
        if MODE_GROUP.get(rmode) != group:
            continue
        own = rmode == mode and rel["tags"].get("ref") == line
        members = _route_members(rel, ways)
        dirs = relation_way_directions(members) if own else [None] * len(members)
        exit_node: int | None = None
        for (w, _role), d in zip(members, dirs):
            nodes = [n for n in w["nodes"] if n in g.coords]
            if not nodes:
                exit_node = None
                continue
            if d is None:  # another line's relation: obey the way's tags
                d, factor = _oneway(w.get("tags", {})), OTHER_LINE_FACTOR
                if group == "rail":
                    d = 0
            else:
                factor = 1.0
                # A hole in the relation: join the previous way's end to this way's start.
                entry = nodes[0] if d == 1 else nodes[-1] if d == -1 else None
                if exit_node is not None and entry is not None and nodes[0] != nodes[-1]:
                    (ax, ay), (bx, by) = g.coords[exit_node], g.coords[entry]
                    if math.hypot(bx - ax, by - ay) <= GAP_MAX_M:
                        g.add_edge(exit_node, entry, 1.0)
                        if reverse_own:
                            g.add_edge(entry, exit_node, REVERSE_OWN_FACTOR)
                exit_node = nodes[-1] if d == 1 else nodes[0] if d == -1 else None
                if nodes[0] == nodes[-1]:
                    exit_node = None
                if reverse_own and d != 0 and _oneway(w.get("tags", {})) in (0, -d):
                    for a, b in zip(nodes, nodes[1:]):
                        if d == 1:
                            g.add_edge(b, a, REVERSE_OWN_FACTOR)
                        else:
                            g.add_edge(a, b, REVERSE_OWN_FACTOR)
            for a, b in zip(nodes, nodes[1:]):
                if d >= 0:
                    g.add_edge(a, b, factor)
                if d <= 0:
                    g.add_edge(b, a, factor)
    return g


def has_own_relation(
    osm_elements: list[dict], line: str, mode: str, stops_lonlat: list[tuple[float, float]]
) -> bool:
    """Whether a relation of this line passes most of the stops, in their order."""
    ways = {e["id"]: e for e in osm_elements if e["type"] == "way" and "geometry" in e}
    xy = [to_xy(lon, lat) for lon, lat in stops_lonlat]
    for rel in osm_elements:
        tags = rel.get("tags", {})
        if rel["type"] != "relation" or tags.get("route") != mode or tags.get("ref") != line:
            continue
        members = _route_members(rel, ways)
        dirs = relation_way_directions(members)
        pts: list[tuple[float, float]] = []
        for (w, _role), d in zip(members, dirs):
            geom = [to_xy(p["lon"], p["lat"]) for p in w["geometry"] if p]
            pts.extend(reversed(geom) if d == -1 else geom)
        if not pts:
            continue
        pos = []
        for x, y in xy:
            dist, i = min((math.hypot(px - x, py - y), i) for i, (px, py) in enumerate(pts))
            if dist <= 100:
                pos.append(i)
        steps = [(b > a) - (b < a) for a, b in zip(pos, pos[1:])]
        if len(pos) * 2 >= len(xy) and sum(steps) > 0:
            return True
    return False


def route_between(
    g: Graph, p: tuple[float, float], q: tuple[float, float]
) -> list[tuple[float, float]] | None:
    """Shortest path in metres-space from point p to point q, or None if not connected."""
    starts, ends = g.snap(*p), g.snap(*q)
    if not starts or not ends:
        return None
    best_direct: tuple[float, list] | None = None
    # Same directed edge, q after p: travel along the edge directly.
    for a, b, t, d, qx, qy in starts:
        for a2, b2, t2, d2, qx2, qy2 in ends:
            if (a, b) == (a2, b2) and t2 >= t:
                cost = math.hypot(qx2 - qx, qy2 - qy) + (d + d2) * SNAP_PENALTY
                if best_direct is None or cost < best_direct[0]:
                    best_direct = (cost, [(qx, qy), (qx2, qy2)])

    # Multi-source A*: leave the start edge at its end node, enter the end edge at its start node.
    target_by_node: dict[int, list[tuple[float, tuple[float, float]]]] = defaultdict(list)
    for a2, b2, t2, d2, qx2, qy2 in ends:
        ax, ay = g.coords[a2]
        target_by_node[a2].append((math.hypot(qx2 - ax, qy2 - ay) + d2 * SNAP_PENALTY, (qx2, qy2)))
    qxq, qyq = q

    def h(n: int) -> float:
        x, y = g.coords[n]
        return math.hypot(x - qxq, y - qyq) * 0.999

    dist: dict[int, float] = {}
    prev: dict[int, int | None] = {}
    start_pt: dict[int, tuple[float, float]] = {}
    heap: list[tuple[float, float, int]] = []
    for a, b, t, d, qx, qy in starts:
        c = (1 - t) * g.adj[a][b] + d * SNAP_PENALTY
        if c < dist.get(b, math.inf):
            dist[b] = c
            prev[b] = None
            start_pt[b] = (qx, qy)
            heapq.heappush(heap, (c + h(b), c, b))

    best: tuple[float, int, tuple[float, float]] | None = None
    limit = best_direct[0] if best_direct else math.inf
    while heap:
        f, c, n = heapq.heappop(heap)
        if c > dist.get(n, math.inf):
            continue
        if f >= min(limit, best[0] if best else math.inf):
            break
        for tc, tpt in target_by_node.get(n, ()):
            if c + tc < (best[0] if best else math.inf):
                best = (c + tc, n, tpt)
        for m, w in g.adj[n].items():
            nc = c + w
            if nc < dist.get(m, math.inf):
                dist[m] = nc
                prev[m] = n
                heapq.heappush(heap, (nc + h(m), nc, m))

    if best is None or (best_direct and best_direct[0] <= best[0]):
        return best_direct[1] if best_direct else None
    _, n, end_pt = best
    path_nodes = []
    cur: int | None = n
    while cur is not None:
        path_nodes.append(cur)
        first = cur
        cur = prev[cur]
    path_nodes.reverse()
    return [start_pt[first]] + [g.coords[x] for x in path_nodes] + [end_pt]


def route_stops(
    g: Graph, stops_lonlat: list[tuple[float, float]]
) -> tuple[list[tuple[float, float]], list[float], int]:
    """Route through all stops. Returns (coords lon/lat, distance along at each stop, fallbacks).

    The line stays on the street: stops on a platform beside the road are not joined to it."""
    xy = [to_xy(lon, lat) for lon, lat in stops_lonlat]
    path: list[tuple[float, float]] = []
    stop_dist = [0.0]
    total = 0.0
    fallbacks = 0

    def extend(pts: list[tuple[float, float]]) -> None:
        nonlocal total
        for b in pts:
            if path:
                a = path[-1]
                dd = math.hypot(b[0] - a[0], b[1] - a[1])
                if dd <= 0.05:
                    continue
                total += dd
            path.append(b)

    for p, q in zip(xy, xy[1:]):
        seg = route_between(g, p, q) if p != q else [p, q]
        straight = math.hypot(q[0] - p[0], q[1] - p[1])
        if seg is None or _length(seg) > 2 * straight + 600:
            seg = [p, q]
            fallbacks += 1
        extend(seg)
        stop_dist.append(total)
    coords = [to_lonlat(x, y) for x, y in path]
    return coords, stop_dist, fallbacks


def _length(pts: list[tuple[float, float]]) -> float:
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:]))
