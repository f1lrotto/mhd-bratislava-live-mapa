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
    assert [derive.delay_band(s) for s in (None, 0, 60, 119, 120, 299, 300, 599, 600, 900)] == [
        None, 0, 0, 0, 1, 1, 2, 2, 3, 3,
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


def test_compaction_after_crash_does_not_duplicate(tmp_path, monkeypatch):
    lg = PollLogger(tmp_path)
    lg.log_poll(T0, [_veh("1"), _veh("2")], 100, None)
    lg.log_poll(T0 + timedelta(seconds=10), [_veh("1"), _veh("2")], 100, None)
    # Crash after the hour file is replaced but before its parts are deleted.
    monkeypatch.setattr(Path, "unlink", lambda self, missing_ok=False: (_ for _ in ()).throw(SystemExit))
    with pytest.raises(SystemExit):
        lg.log_poll(T0 + timedelta(seconds=40), [_veh("1")], 100, None)
    monkeypatch.undo()
    PollLogger(tmp_path)  # restart compacts the leftover parts again
    t = pq.read_table(tmp_path / "vehicles" / "date=2026-11-16" / "hour=16.parquet")
    assert t.num_rows == 4


def test_unexpected_feed_error_is_logged(tmp_path):
    import asyncio

    async def bad_fetch(_client):
        return feed.parse_feed([{"Key": "1", "Location": [48.1, 17.1]}, {"Key": "2", "Location": "x"}])

    p = Poller(PollLogger(tmp_path), fetch=bad_fetch)
    asyncio.run(p.poll_once(None))
    assert p.snapshot.error and p.snapshot.attempted_at is not None
    polls = pq.ParquetDataset(tmp_path / "polls").read().to_pylist()
    assert [r["ok"] for r in polls] == [False]


def test_api_live_feed_down():
    from fastapi.testclient import TestClient

    from mhd.app import create_app

    p = Poller(logger=None)
    old = datetime.now(timezone.utc) - timedelta(minutes=4)
    p.apply([_veh()], old)
    with TestClient(create_app(poller=p, start_polling=False)) as c:
        body = c.get("/api/live").json()
    assert body["feed"]["down"] is True
    assert body["regionalFeed"]["down"] is True  # no IDS BK sweep yet
    assert body["vehicles"][0]["line"] == "83"


def test_heartbeat_reports_each_source():
    """The monitor's alerts count these: each source's own freshness and vehicles."""
    from mhd import heartbeat

    p = Poller(logger=None)
    p.apply([_veh("1"), _veh("2"), _veh("3")], T0)
    p.apply_regional(T0 - timedelta(minutes=10), [_veh(feed.REGIONAL + "9")])
    p.apply_regional(T0, None, "timeout")
    now = T0 + timedelta(seconds=20)
    by_source = {e["properties"]["source"]: e["properties"] for e in heartbeat.events(p, now, regional=True)}
    assert by_source["dpb"] == {"source": "dpb", "ok": True, "vehicles": 3, "age_s": 20, "error": None,
                                "$process_person_profile": False}
    assert by_source["idsbk"]["ok"] is False and by_source["idsbk"]["vehicles"] == 1
    assert by_source["idsbk"]["age_s"] == 620 and by_source["idsbk"]["error"] == "timeout"
    assert [e["properties"]["source"] for e in heartbeat.events(p, now, regional=False)] == ["dpb"]


def _record(vid, line, lat, lon, trip=1, delay=0, urban=False, train=False):
    """A record of the IDS BK map's vehicles/nearby endpoint (fields we don't read left out)."""
    return {"vehicleID": vid, "delayMinutes": delay, "latitude": lat, "longitude": lon,
            "timeTableTrip": {"tripID": vid, "trip": trip, "destination": "Pezinok, aut. st.",
                              "timeTableLine": {"line": line, "ezIsTrain": train, "ezIsUrban": urban}}}


def test_regional_sweep_finds_every_bus_beyond_the_nearest_100():
    """The endpoint answers with the 100 vehicles nearest a point. City vehicles crowd Bratislava,
    so the sweep has to split its tiles until it has reached every regional bus in the area."""
    import asyncio
    import random

    from mhd import idsbk
    from mhd.poller import distance_m

    rnd = random.Random(1)
    lat0, lat1, lon0, lon1 = idsbk.AREA
    world = [_record(i, "83", 48.15 + rnd.uniform(-0.03, 0.03), 17.11 + rnd.uniform(-0.05, 0.05), urban=True)
             for i in range(400)]
    world += [_record(1000 + i, str(500 + i), rnd.uniform(lat0, lat1), rnd.uniform(lon0, lon1), trip=i, delay=i)
              for i in range(40)]
    world += [_record(1100 + i, "520", 48.15 + rnd.uniform(-0.03, 0.03), 17.11 + rnd.uniform(-0.05, 0.05))
              for i in range(5)]  # regional buses in the city, among the trams
    world.append(_record(2000, "S50", 48.3, 17.3, train=True))
    calls = []

    async def fetch(_client, lat, lon):
        calls.append((lat, lon))
        return sorted(world, key=lambda r: distance_m(lat, lon, r["latitude"], r["longitude"]))[: idsbk.CAP]

    async def no_sleep(_s):
        pass

    got = []
    s = idsbk.Sweeper(None, lambda ts, vs, err: got.append((vs, err)), fetch=fetch, sleep=no_sleep)
    asyncio.run(s.sweep_once(None))
    vs, err = got[0]
    assert err is None
    want = [f"idsbk:{1000 + i}" for i in range(40)] + [f"idsbk:{1100 + i}" for i in range(5)]
    assert sorted(v.key for v in vs) == sorted(want)
    v = next(v for v in vs if v.key == "idsbk:1012")
    assert (v.line, v.trip_no, v.delay_s, v.type) == ("512", 12, 720, "bus")
    first = len(calls)
    assert first <= idsbk.MAX_REQUESTS
    # The next sweep starts from the tiles the first one ended with instead of splitting again.
    asyncio.run(s.sweep_once(None))
    assert len(got[1][0]) == 45 and len(calls) - first < first


def test_regional_sweeps_merge_into_the_snapshot_and_a_failed_one_keeps_the_last():
    p = Poller(logger=None)
    reg = feed.Vehicle("idsbk:7", "512", "Pezinok", "bus", 48.3, 17.27, 1200, None, None, trip_no=12)
    p.apply([_veh()], T0)
    p.apply_regional(T0 + timedelta(seconds=10), [reg])
    p.apply([_veh(lat=48.151)], T0 + timedelta(seconds=15))  # DPB polls again: the regional bus stays
    assert [v.key for v in p.snapshot.vehicles] == ["1", "idsbk:7"]
    assert p.snapshot.seen_at("1") == T0 + timedelta(seconds=15)
    assert p.snapshot.seen_at("idsbk:7") == T0 + timedelta(seconds=10)

    now = T0 + timedelta(minutes=4)
    p.apply([_veh(lat=48.152)], now)
    p.apply_regional(now, None, "SweepError: HTTP 503")
    snap = p.snapshot
    assert [v.key for v in snap.vehicles] == ["1", "idsbk:7"]
    status = derive.feed_status(snap.regional, now)
    assert status["down"] and status["error"] == "SweepError: HTTP 503"
    assert not derive.feed_status(snap, now)["down"]
    j = derive.vehicle_json(snap.vehicles[1], snap, now)
    # 20 minutes is a regional bus's real delay, not DPB's "15 min or more".
    assert j["regional"] and j["tripNo"] == 12 and not j["delayCapped"] and j["band"] == 3
