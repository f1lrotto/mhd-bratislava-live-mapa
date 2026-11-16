import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pyarrow.parquet as pq
import pytest

os.environ.setdefault("MHD_NO_POLL", "1")

from mhd import derive, feed  # noqa: E402
from mhd.logger import PollLogger  # noqa: E402
from mhd.poller import Poller  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "feed_sample.json"
T0 = datetime(2026, 11, 16, 16, 59, 30, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "raw,expected",
    [("0:00", 0), ("2:05", 125), ("15:00", 900), ("1:02:03", 3723), ("-0:30", -30), (None, None), ("x", None)],
)
def test_parse_delay(raw, expected):
    assert feed.parse_delay(raw) == expected


def test_parse_feed_sample():
    raw = json.loads(FIXTURE.read_text())
    vs = feed.parse_feed(raw)
    assert len(vs) == len(raw)
    by_key = {v.key: v for v in vs}
    r = raw[0]
    v = by_key[r["Key"]]
    assert (v.lat, v.lon) == (round(r["Location"]["Latitude"], 6), round(r["Location"]["Longitude"], 6))
    assert {v.type for v in vs} == {"bus", "tram", "trolleybus"}
    # 510 is the feed's "no heading" value, not 150°.
    for r in raw:
        if r["Azimuth"] == 510:
            assert by_key[r["Key"]].azimuth is None
    assert any(v.delay_s == 900 for v in vs)


def test_parse_feed_rejects_empty():
    with pytest.raises(feed.FeedError):
        feed.parse_feed([])
    with pytest.raises(feed.FeedError):
        feed.parse_feed({"error": "ticket"})


def _veh(key="1", lat=48.15, lon=17.1, line="83", az=None):
    return feed.Vehicle(key, line, "Pri kríži", "bus", lat, lon, 120, 1, az)


def test_stale_and_heading():
    p = Poller(logger=None)
    p.apply([_veh()], T0)
    # Jitter of a few metres for 10 minutes is not movement.
    p.apply([_veh(lat=48.15002)], T0 + timedelta(minutes=10))
    now = T0 + timedelta(minutes=10)
    j = derive.vehicle_json(p.snapshot.vehicles[0], p.snapshot, now)
    assert j["stale"] is True and j["movedAgo"] == 600
    # Moving 100 m east clears staleness and gives a heading of about 90°.
    p.apply([_veh(lon=17.10135)], now + timedelta(seconds=30))
    j = derive.vehicle_json(p.snapshot.vehicles[0], p.snapshot, now + timedelta(seconds=30))
    assert j["stale"] is False and j["az"] in (89, 90, 91)
    # Without a line, a parked vehicle is never stale.
    p.apply([_veh(lon=17.10135, line=None)], now + timedelta(minutes=30))
    j = derive.vehicle_json(p.snapshot.vehicles[0], p.snapshot, now + timedelta(minutes=30))
    assert j["stale"] is False


def test_delay_band_boundaries():
    assert [derive.delay_band(s) for s in (None, 0, 59, 60, 179, 180, 599, 600, 900)] == [
        None, 0, 0, 1, 1, 2, 2, 3, 3,
    ]


def test_logger_parts_and_compaction(tmp_path):
    lg = PollLogger(tmp_path)
    vs = [_veh("1"), _veh("2")]
    lg.log_poll(T0, vs, 120, None)
    lg.log_poll(T0 + timedelta(seconds=15), None, 20000, "FeedError: HTTP 403")
    hour16 = tmp_path / "vehicles" / "date=2026-11-16"
    assert len(list(hour16.glob("hour=16.part-*.parquet"))) == 1
    # The next hour's first poll compacts hour 16.
    lg.log_poll(T0 + timedelta(seconds=40), vs, 100, None)
    assert not list(hour16.glob("hour=16.part-*"))
    t = pq.read_table(hour16 / "hour=16.parquet")
    assert t.num_rows == 2 and t.column("key").to_pylist() == ["1", "2"]
    polls = pq.read_table(tmp_path / "polls" / "date=2026-11-16" / "hour=16.parquet").to_pylist()
    assert [p["ok"] for p in polls] == [True, False]
    assert polls[1]["error"] == "FeedError: HTTP 403"
    # Hour 17 is still in progress and stays as a part file until a restart or rollover.
    assert len(list((tmp_path / "vehicles" / "date=2026-11-16").glob("hour=17.part-*"))) == 1
    PollLogger(tmp_path).compact_finished(now=T0 + timedelta(hours=2))
    assert (hour16 / "hour=17.parquet").exists()


def test_api_live_feed_down():
    from fastapi.testclient import TestClient

    from mhd.app import create_app

    p = Poller(logger=None)
    old = datetime.now(timezone.utc) - timedelta(minutes=4)
    p.apply([_veh()], old)
    with TestClient(create_app(poller=p, start_polling=False)) as c:
        body = c.get("/api/live").json()
    assert body["feed"]["down"] is True
    assert body["vehicles"][0]["line"] == "83"
