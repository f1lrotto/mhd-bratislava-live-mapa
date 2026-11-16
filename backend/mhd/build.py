"""Static build: routes, stops and scheduled departures from the DPB GTFS, routed along OSM streets.

    uv run python -m mhd.build [--force]

It writes <data>/static/ and only rebuilds when the GTFS feed_version changes (or with --force):

    meta.json     feed version, build time, OSM timestamp, routing fallbacks per line
    lines.json    every line: type, colours, directions (headsigns, stop ids, stop distances)
    shapes.json   {line: {direction: [[lon, lat], ...]}} street-following geometry
    stops.json    every stop: name, position, lines serving it
    service.json  calendar (weekday pattern, date range, exceptions) and first-stop departures
                  per line, direction and service, in seconds after midnight
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
                if len(data["elements"]) > 100:
                    return data
            log.warning("overpass attempt %d: HTTP %s", attempt + 1, r.status_code)
        except httpx.HTTPError as e:
            log.warning("overpass attempt %d: %s", attempt + 1, e)
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

    # Stop sequence and first departure of every trip.
    seq: dict[str, list[tuple[int, str]]] = defaultdict(list)
    first_dep: dict[str, tuple[int, int]] = {}
    last_arr: dict[str, tuple[int, int]] = {}
    for st in gtfs["stop_times"]:
        tid = st["trip_id"]
        n = int(st["stop_sequence"])
        seq[tid].append((n, st["stop_id"]))
        dep = st["departure_time"] or st["arrival_time"]
        if dep and (tid not in first_dep or n < first_dep[tid][0]):
            first_dep[tid] = (n, _secs(dep))
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

    lines: dict[str, dict] = {}
    shapes: dict[str, dict[str, list]] = defaultdict(dict)
    departures: dict[str, dict[str, dict[str, list[int]]]] = defaultdict(lambda: defaultdict(dict))
    stop_lines: dict[str, set[str]] = defaultdict(set)
    fallbacks: dict[str, int] = {}
    graphs: dict[tuple[str, str], osmroute.Graph] = {}

    for (line, direction), trips in sorted(groups.items()):
        r = routes[trips[0]["route_id"]]
        mode = ROUTE_TYPES.get(r["route_type"], "bus")
        # The direction's main pattern is its most common stop sequence.
        # Patterns that never leave one stop (line 27's loop has a "direction 1" made of such
        # stubs) are not routes.
        patterns = Counter(
            p
            for p in (tuple(s for _, s in sorted(seq[t["trip_id"]])) for t in trips)
            if len(set(p)) >= 2
        )
        if not patterns:
            continue
        main = list(patterns.most_common(1)[0][0])
        headsigns = Counter(t["trip_headsign"] for t in trips if t["trip_headsign"])
        main_headsign = Counter(
            t["trip_headsign"]
            for t in trips
            if tuple(s for _, s in sorted(seq[t["trip_id"]])) == tuple(main)
        ).most_common(1)[0][0]

        key = (line, mode)
        if key not in graphs:
            graphs[key] = osmroute.build_graph(osm["elements"], line, mode)
        pts = [(float(stops[s]["stop_lon"]), float(stops[s]["stop_lat"])) for s in main]
        coords, stop_dist, fb = osmroute.route_stops(graphs[key], pts)
        fallbacks[line] = fallbacks.get(line, 0) + fb
        shapes[line][direction] = [[round(x, 6), round(y, 6)] for x, y in coords]

        # Every stop served in this direction gets a distance along the main pattern, so short
        # turns and variants can be placed on the ribbon too.
        poly = Polyline(coords)
        for t in trips:
            for _, s in seq[t["trip_id"]]:
                stop_lines[s].add(line)
        for t in trips:
            if t["trip_id"] in first_dep:
                departures[line][direction].setdefault(t["service_id"], []).append(
                    first_dep[t["trip_id"]][1]
                )

        info = lines.setdefault(
            line,
            {
                "line": line,
                "type": mode,
                "color": "#" + (r["route_color"] or "888888"),
                "textColor": "#" + (r["route_text_color"] or "FFFFFF"),
                "directions": {},
            },
        )
        info["directions"][direction] = {
            "headsign": main_headsign,
            "headsigns": sorted(headsigns),
            "from": stops[main[0]]["stop_name"],
            "stops": main,
            "stopDist": [round(d) for d in stop_dist],
            "length": round(poly.length),
            # Median scheduled run time of the main pattern, used to turn distance gaps into time.
            "duration": _median_duration(
                [t for t in trips if tuple(s for _, s in sorted(seq[t["trip_id"]])) == tuple(main)],
                first_dep,
                last_arr,
            ),
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
        "stops": out_stops,
        "service": {"calendar": calendar, "departures": departures},
    }


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
    for name in ("meta", "lines", "shapes", "stops", "service"):
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
