"""Fetching and parsing the DPB vehicle feed.

The feed is undocumented. A record looks like:
{"Key":"1843","Label":"98","TransportTypeCode":"T","Location":{"Latitude":48.18,"Longitude":17.16},
 "LineName":"98","FinalStationName":"Depo Jurajov dvor","Delay":"0:00","Azimuth":330,"State":0}
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import httpx

FEED_URL = os.environ.get(
    "MHD_FEED_URL",
    "https://skeleton.dpb.sk/Infotainment/VehicleState/__VehicleStateMapData"
    "?_ticket=973e3385-98cc-47a2-bb26-993fa41f26d2",
)

TYPE_CODES = {"A": "tram", "O": "trolleybus", "T": "bus"}

# The feed never reports more than 15:00; that value means "15 min or more, or unknown".
DELAY_CAP_S = 15 * 60


@dataclass(slots=True)
class Vehicle:
    key: str
    line: str | None
    dest: str | None
    type: str  # tram | trolleybus | bus | other
    lat: float
    lon: float
    delay_s: int | None
    state: int | None
    azimuth: int | None


class FeedError(Exception):
    pass


def parse_delay(value: str | None) -> int | None:
    """Parse "m:ss" (or "h:mm:ss") into seconds. Returns None for missing or malformed values."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    sign = -1 if s.startswith("-") else 1
    parts = s.lstrip("+-").split(":")
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return None
    if len(nums) == 2:
        m, sec = nums
        total = m * 60 + sec
    elif len(nums) == 3:
        h, m, sec = nums
        total = h * 3600 + m * 60 + sec
    else:
        return None
    return sign * total


def _clean(s: object) -> str | None:
    if s is None:
        return None
    s = str(s).strip()
    return s or None


def parse_record(r: dict) -> Vehicle | None:
    key = _clean(r.get("Key"))
    loc = r.get("Location") or {}
    lat, lon = loc.get("Latitude"), loc.get("Longitude")
    if key is None or lat is None or lon is None:
        return None
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return None
    if lat == 0 and lon == 0:
        return None
    # 0–359 are bearings. 510 (41% of vehicles on 16 Nov) means "no heading", so any value
    # outside 0–359 is unknown rather than taken mod 360.
    az = r.get("Azimuth")
    try:
        az = int(az) if az is not None else None
    except (TypeError, ValueError):
        az = None
    if az is not None and not 0 <= az < 360:
        az = None
    state = r.get("State")
    return Vehicle(
        key=key,
        line=_clean(r.get("LineName")) or _clean(r.get("Label")),
        dest=_clean(r.get("FinalStationName")),
        type=TYPE_CODES.get(_clean(r.get("TransportTypeCode")) or "", "other"),
        lat=round(lat, 6),
        lon=round(lon, 6),
        delay_s=parse_delay(r.get("Delay")),
        state=state if isinstance(state, int) else None,
        azimuth=az,
    )


def parse_feed(payload: object) -> list[Vehicle]:
    if not isinstance(payload, list):
        raise FeedError(f"unexpected payload type {type(payload).__name__}")
    out: list[Vehicle] = []
    seen: set[str] = set()
    for r in payload:
        if not isinstance(r, dict):
            continue
        v = parse_record(r)
        if v is None or v.key in seen:
            continue
        seen.add(v.key)
        out.append(v)
    if not out:
        raise FeedError("feed returned no vehicles")
    return out


async def fetch(client: httpx.AsyncClient) -> list[Vehicle]:
    resp = await client.get(FEED_URL)
    if resp.status_code != 200:
        raise FeedError(f"HTTP {resp.status_code}")
    try:
        payload = resp.json()
    except ValueError as e:
        raise FeedError(f"invalid JSON: {e}") from e
    return parse_feed(payload)
