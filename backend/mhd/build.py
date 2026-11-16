"""Static build: routes, stops and scheduled departures from the DPB GTFS, routed along OSM streets.

    uv run python -m mhd.build [--force]

It writes <data>/static/ and only rebuilds when the GTFS feed_version changes (or with --force):

    meta.json     feed version, build time, OSM timestamp, routing fallbacks per line
    lines.json    every line: type, colours, directions (headsigns, stop ids, stop distances).
                  Direction ids are DPB's direction_id ("0", "1"), plus "0-2", "1-3"… for the
                  legs of loop lines and for branches that leave the main route to another
                  headsign. refStop is the index of the stop the departures are timed at
    shapes.json   {line: {direction: [[lon, lat], ...]}} street-following geometry of the main pattern
    branches.json {line: {direction: [[[lon, lat], ...], ...]}} extra shapes of branches that end at
                  the direction's headsign (line 4 from Stn. Nové Mesto); only directions with any
    stops.json    every stop: name, position, lines serving it
    service.json  calendar (weekday pattern, date range, exceptions) and departures at each
                  direction's reference stop per line, direction and service, in seconds after
                  midnight
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import logging
import math
import os
import time
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import httpx

from . import osmroute
from .geo import Polyline

log = logging.getLogger("mhd.build")

GTFS_URL = os.environ.get(
    "MHD_GTFS_URL",
    "https://www.arcgis.com/sharing/rest/content/items/aba12fd2cbac4843bc7406151bc66106/data",
)
OVERPASS_URL = os.environ.get("MHD_OVERPASS_URL", "https://overpass-api.de/api/interpreter")
OVERPASS_QUERY = """[out:json][timeout:180];
relation["type"="route"]["route"~"^(bus|tram|trolleybus)$"]["network"="MHD Bratislava"](48.03,16.95,48.27,17.25)->.r;
.r out body;
way(r.r);
out body geom;"""
USER_AGENT = "mhd-nazivo-build/0.1 (github.com/f1lrotto/mhd-bratislava-live-mapa)"

MIN_SHARE = 0.15  # share of trips a pattern needs to become a direction (or branch) of its own
BRANCH_OFF_M = 150.0  # a variant with a stop this far from the main shape is drawn as a branch
MIN_LENGTH_M = 300.0  # directions shorter than this are stubs (depot pull-outs), not routes

ROUTE_TYPES = {"0": "tram", "3": "bus", "11": "trolleybus", "800": "trolleybus"}


def _read_csv(z: zipfile.ZipFile, name: str) -> list[dict]:
    with z.open(name) as f:
        return list(csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig")))


def _secs(hms: str) -> int:
    h, m, s = (int(x) for x in hms.split(":"))
    return h * 3600 + m * 60 + s


def fetch_overpass(client: httpx.Client) -> dict:
    delay = 10
    for attempt in range(6):
        try:
            r = client.post(OVERPASS_URL, data={"data": OVERPASS_QUERY}, timeout=240)
            if r.status_code == 200 and '"elements"' in r.text[:2000]:
                data = r.json()
                # A "remark" means the query timed out or ran out of memory: the result is partial.
                if "remark" in data:
                    log.warning("overpass attempt %d: %s", attempt + 1, data["remark"])
                elif len(data["elements"]) > 100:
                    return data
            log.warning("overpass attempt %d: HTTP %s", attempt + 1, r.status_code)
        except (httpx.HTTPError, ValueError) as e:
            log.warning("overpass attempt %d: %s", attempt + 1, e)
        if attempt < 5:
            time.sleep(delay)
            delay *= 2
    raise RuntimeError("Overpass API unavailable")


def load_gtfs(zip_bytes: bytes) -> dict:
    z = zipfile.ZipFile(io.BytesIO(zip_bytes))
    return {
        "feed_info": _read_csv(z, "feed_info.txt"),
        "routes": _read_csv(z, "routes.txt"),
        "trips": _read_csv(z, "trips.txt"),
        "stops": _read_csv(z, "stops.txt"),
        "stop_times": _read_csv(z, "stop_times.txt"),
        "calendar": _read_csv(z, "calendar.txt"),
        "calendar_dates": _read_csv(z, "calendar_dates.txt"),
    }


def build(gtfs: dict, osm: dict) -> dict:
    routes = {r["route_id"]: r for r in gtfs["routes"]}
    stops = {s["stop_id"]: s for s in gtfs["stops"]}

    # Stop sequence with departure times, first departure and last arrival of every trip.
    seq: dict[str, list[tuple[int, str, int | None]]] = defaultdict(list)
    first_dep: dict[str, tuple[int, int]] = {}
    last_arr: dict[str, tuple[int, int]] = {}
    for st in gtfs["stop_times"]:
        tid = st["trip_id"]
        n = int(st["stop_sequence"])
        dep = st["departure_time"] or st["arrival_time"]
        dep_s = _secs(dep) if dep else None
        seq[tid].append((n, st["stop_id"], dep_s))
        if dep and (tid not in first_dep or n < first_dep[tid][0]):
            first_dep[tid] = (n, dep_s)
        arr = st["arrival_time"] or st["departure_time"]
        if arr and (tid not in last_arr or n > last_arr[tid][0]):
            last_arr[tid] = (n, _secs(arr))

    # Group trips by line and direction.
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for t in gtfs["trips"]:
        r = routes.get(t["route_id"])
        if r is None or t["trip_id"] not in seq:
            continue
        groups[(r["route_short_name"], t["direction_id"] or "0")].append(t)

    for v in seq.values():
        v.sort(key=lambda x: x[0])
    pattern = {tid: tuple(s for _, s, _ in v) for tid, v in seq.items()}
    lonlat = {s: (float(v["stop_lon"]), float(v["stop_lat"])) for s, v in stops.items()}
    lines: dict[str, dict] = {}
    shapes: dict[str, dict[str, list]] = defaultdict(dict)
    branches: dict[str, dict[str, list]] = defaultdict(dict)
    departures: dict[str, dict[str, dict[str, list[int]]]] = defaultdict(lambda: defaultdict(dict))
    stop_lines: dict[str, set[str]] = defaultdict(set)
    fallbacks: dict[str, int] = {}
    graphs: dict[tuple[str, str, bool], osmroute.Graph] = {}
    line_dirs: dict[str, list[dict]] = defaultdict(list)

    def route(line: str, mode: str, main: tuple[str, ...]) -> tuple[list, list[float], int]:
        pts = [lonlat[s] for s in main]
        # Without a relation of its own in this direction, the line's relations for the other
        # direction can be travelled backwards.
        key = (line, mode, not osmroute.has_own_relation(osm["elements"], line, mode, pts))
        if key not in graphs:
            graphs[key] = osmroute.build_graph(osm["elements"], *key)
        return osmroute.route_stops(graphs[key], pts)

    # DPB's direction_id is not always a direction: on loop lines (57, 69) one id holds legs that
    # run opposite ways and the other only depot stubs. So each id is split into clusters of stop
    # patterns that run the same way; each cluster's most common pattern is its main pattern.
    for (line, did), trips in sorted(groups.items()):
        r = routes[trips[0]["route_id"]]
        mode = ROUTE_TYPES.get(r["route_type"], "bus")
        if any(k[0] != line for k in graphs):  # graphs are per line and each holds the whole network
            graphs.clear()
        for t in trips:
            for s in pattern[t["trip_id"]]:
                stop_lines[s].add(line)
        by_pat: dict[tuple[str, ...], list[dict]] = defaultdict(list)
        for t in trips:
            if len(set(pattern[t["trip_id"]])) >= 2:
                by_pat[pattern[t["trip_id"]]].append(t)
        pats = sorted(by_pat, key=lambda p: -len(by_pat[p]))
        clusters: list[dict] = []
        for p in pats:  # patterns common enough to be a direction, running unlike the ones so far
            if (
                len(set(p)) >= 2
                and (not clusters or len(by_pat[p]) >= MIN_SHARE * len(trips))
                and all(_order_score(c["pos"], p) <= 0 for c in clusters)
            ):
                clusters.append({"main": p, "pos": _positions(p), "pats": [p]})
        for p in pats:  # the rest are variants of the cluster they run along, or dropped
            best = max(clusters, key=lambda c: _order_score(c["pos"], p), default=None)
            if best is not None and p not in best["pats"] and _order_score(best["pos"], p) > 0:
                best["pats"].append(p)

        cands = []
        for c in clusters:
            coords, stop_dist, fb = route(line, mode, c["main"])
            poly = Polyline(coords)
            if poly.length < MIN_LENGTH_M:  # a stub, e.g. a depot pull-out
                continue
            out = [{"main": c["main"], "coords": coords, "stopDist": stop_dist, "fb": fb, "pats": c["pats"]}]
            # A common variant with stops away from the main shape (line 4's Stn. Nové Mesto
            # terminal) gets a shape of its own. Other variants' stops are not placed.
            ctrips = sum(len(by_pat[p]) for p in c["pats"])
            for p in c["pats"][1:]:
                if len(by_pat[p]) >= MIN_SHARE * ctrips and max(poly.project(*lonlat[s])[1] for s in p) > BRANCH_OFF_M:
                    bc, bd, bfb = route(line, mode, p)
                    out[0]["pats"] = [q for q in out[0]["pats"] if q != p]
                    out.append({"main": p, "coords": bc, "stopDist": bd, "fb": bfb, "pats": [p]})
            cands.extend(out)

        # Groups that end at the same headsign or final stop are one direction (line 4's trams
        # from Zlaté piesky and from Stn. Nové Mesto both run to Pri kríži): the group with most
        # trips is its main pattern, the others are branch shapes drawn beside it.
        merged: list[list[dict]] = []
        for d in cands:
            d["trips"] = [t for q in d["pats"] for t in by_pat[q]]
            d["headsign"] = Counter(t["trip_headsign"] for t in by_pat[d["main"]]).most_common(1)[0][0]
            d["end"] = stops[d["main"][-1]]["stop_name"]
            same = next((m for m in merged if any(d["headsign"] == e["headsign"] or d["end"] == e["end"] for e in m)), None)
            if same is None:
                merged.append([d])
            else:
                same.append(d)
        for n, m in enumerate(merged, 1):
            m.sort(key=lambda e: -len(e["trips"]))
            d = {**m[0], "branches": [e["coords"] for e in m[1:]], "fb": sum(e["fb"] for e in m)}
            d["pats"] = [q for e in m for q in e["pats"]]
            d["trips"] = [t for e in m for t in e["trips"]]
            d["id"] = did if n == 1 else f"{did}-{n}"
            d["route"] = r
            d["mode"] = mode
            line_dirs[line].append(d)

    for line, dirs in line_dirs.items():
        # A headsign belongs to the direction with most of its trips, and also to any direction
        # with at least half as many (ambiguous; matching then decides by position and heading).
        # A direction always keeps its main headsign, so a branch's vehicles can match it.
        counts = [Counter(t["trip_headsign"] for t in d["trips"] if t["trip_headsign"]) for d in dirs]
        top = Counter()
        for cnt in counts:
            for h, k in cnt.items():
                top[h] = max(top[h], k)
        for d, cnt in zip(dirs, counts):
            main, r = d["main"], d["route"]
            did = d["id"]
            fallbacks[line] = fallbacks.get(line, 0) + d["fb"]
            shapes[line][did] = [[round(x, 6), round(y, 6)] for x, y in d["coords"]]
            if d["branches"]:
                branches[line][did] = [[[round(x, 6), round(y, 6)] for x, y in b] for b in d["branches"]]
            main_trips = [t for t in d["trips"] if pattern[t["trip_id"]] == main]
            origin = stops[main[0]]["stop_name"]
            # Interval departures at one reference stop: the main-pattern stop passed by most of the
            # direction's trips, branches and trips starting partway along included.
            served = Counter(s for t in d["trips"] for s in set(pattern[t["trip_id"]]))
            ref = max(range(len(main)), key=lambda i: (served[main[i]], -i))
            for t in d["trips"]:
                dep = next((x for _, s, x in seq[t["trip_id"]] if s == main[ref]), None)
                if dep is not None:
                    departures[line][did].setdefault(t["service_id"], []).append(dep)
            info = lines.setdefault(
                line,
                {
                    "line": line,
                    "type": d["mode"],
                    "color": "#" + (r["route_color"] or "888888"),
                    "textColor": "#" + (r["route_text_color"] or "FFFFFF"),
                    "directions": {},
                },
            )
            headsign = Counter(t["trip_headsign"] for t in main_trips).most_common(1)[0][0]
            info["directions"][did] = {
                "headsign": headsign,
                "headsigns": sorted(h for h, k in cnt.items() if 2 * k >= top[h] or h == headsign),
                "from": origin,
                "stops": list(main),
                "stopDist": [round(x) for x in d["stopDist"]],
                "length": round(Polyline(d["coords"]).length),
                # Median scheduled run time of the main pattern, used to turn distance gaps into time.
                "duration": _median_duration(main_trips, first_dep, last_arr),
                # Index in `stops` of the stop the interval departures are timed at.
                "refStop": ref,
            }

    for line in departures:
        for direction in departures[line]:
            for sid in departures[line][direction]:
                departures[line][direction][sid].sort()

    out_stops = {
        s["stop_id"]: {
            "name": s["stop_name"],
            "code": s["stop_code"],
            "platform": s["platform_code"] or None,
            "lat": round(float(s["stop_lat"]), 6),
            "lon": round(float(s["stop_lon"]), 6),
            "lines": sorted(stop_lines[s["stop_id"]], key=_line_sort_key),
        }
        for s in gtfs["stops"]
        if s["stop_id"] in stop_lines
    }

    calendar = {
        c["service_id"]: {
            "days": [int(c[d]) for d in ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")],
            "start": c["start_date"],
            "end": c["end_date"],
            "added": [],
            "removed": [],
        }
        for c in gtfs["calendar"]
    }
    for cd in gtfs["calendar_dates"]:
        c = calendar.setdefault(
            cd["service_id"], {"days": [0] * 7, "start": "", "end": "", "added": [], "removed": []}
        )
        c["added" if cd["exception_type"] == "1" else "removed"].append(cd["date"])

    feed_info = gtfs["feed_info"][0] if gtfs["feed_info"] else {}
    meta = {
        "feedVersion": feed_info.get("feed_version"),
        "feedEnd": feed_info.get("feed_end_date"),
        "builtAt": datetime.now(timezone.utc).isoformat(),
        "osmTimestamp": osm.get("osm3s", {}).get("timestamp_osm_base"),
        "fallbacks": {k: v for k, v in fallbacks.items() if v},
    }
    return {
        "meta": meta,
        "lines": dict(sorted(lines.items(), key=lambda kv: _line_sort_key(kv[0]))),
        "shapes": shapes,
        "branches": branches,
        "stops": out_stops,
        "service": {"calendar": calendar, "departures": departures},
    }


def _positions(p: tuple[str, ...]) -> dict[str, int]:
    """First index of each stop in a pattern."""
    pos: dict[str, int] = {}
    for i, s in enumerate(p):
        pos.setdefault(s, i)
    return pos


def _order_score(pos: dict[str, int], p: tuple[str, ...]) -> int:
    """Consecutive shared stops of `p` in the same order as `pos`, minus those in the opposite
    order. Positive when p runs the same way as the pattern `pos` was made from."""
    seen = [pos[s] for s in p if s in pos]
    return sum((b > a) - (b < a) for a, b in zip(seen, seen[1:]))


def _median_duration(trips: list[dict], first_dep: dict, last_arr: dict) -> int | None:
    ds = sorted(
        last_arr[t["trip_id"]][1] - first_dep[t["trip_id"]][1]
        for t in trips
        if t["trip_id"] in first_dep and t["trip_id"] in last_arr
    )
    ds = [d for d in ds if d > 0]
    return ds[len(ds) // 2] if ds else None


def _line_sort_key(line: str) -> tuple:
    """Day lines numerically, then night lines (N..), then the rest."""
    if line.isdigit():
        return (0, int(line), line)
    if line.startswith("N") and line[1:].isdigit():
        return (1, int(line[1:]), line)
    return (2, 0, line)


def write(out: dict, static_dir: Path) -> None:
    static_dir.mkdir(parents=True, exist_ok=True)
    # meta.json last: the app reloads when it changes, so the other files must already be new.
    for name in ("lines", "shapes", "branches", "stops", "service", "meta"):
        tmp = static_dir / f".{name}.json.tmp"
        tmp.write_text(json.dumps(out[name], ensure_ascii=False, separators=(",", ":")))
        os.replace(tmp, static_dir / f"{name}.json")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="rebuild even if the GTFS version is unchanged")
    ap.add_argument("--cached-osm", action="store_true", help="reuse cache/osm.json instead of Overpass")
    ap.add_argument("--data-dir", default=os.environ.get("MHD_DATA_DIR", Path(__file__).resolve().parents[2] / "data"))
    args = ap.parse_args()
    data = Path(args.data_dir)
    static_dir, cache = data / "static", data / "cache"
    cache.mkdir(parents=True, exist_ok=True)

    with httpx.Client(headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=120) as client:
        log.info("downloading GTFS")
        r = client.get(GTFS_URL)
        r.raise_for_status()
        gtfs = load_gtfs(r.content)
        version = (gtfs["feed_info"] or [{}])[0].get("feed_version")
        meta_path = static_dir / "meta.json"
        if not args.force and meta_path.exists():
            if json.loads(meta_path.read_text()).get("feedVersion") == version:
                log.info("GTFS %s already built, nothing to do", version)
                return
        (cache / "gtfs.zip").write_bytes(r.content)
        osm_path = cache / "osm.json"
        if args.cached_osm and osm_path.exists():
            osm = json.loads(osm_path.read_text())
        else:
            try:
                log.info("downloading OSM route relations")
                osm = fetch_overpass(client)
                osm_path.write_text(json.dumps(osm))
            except RuntimeError:
                if not osm_path.exists():
                    raise
                log.warning("Overpass unavailable, using cached OSM data")
                osm = json.loads(osm_path.read_text())

    t0 = time.monotonic()
    out = build(gtfs, osm)
    write(out, static_dir)
    log.info(
        "built %d lines, %d stops in %.1f s; straight-line fallbacks: %s",
        len(out["lines"]),
        len(out["stops"]),
        time.monotonic() - t0,
        out["meta"]["fallbacks"] or "none",
    )


if __name__ == "__main__":
    main()
