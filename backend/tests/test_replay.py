from datetime import datetime, timedelta, timezone

import pyarrow.compute as pc
import pyarrow.parquet as pq
from fastapi.testclient import TestClient

import mhd.app
from mhd.feed import Vehicle
from mhd.logger import PollLogger
from mhd.poller import Poller

UTC = timezone.utc
T0 = datetime(2026, 11, 13, 15, 50, tzinfo=UTC)  # Friday 16:50 in Bratislava


def _decode(v: dict, start: int, strings: list[str]) -> list[tuple]:
    out, t, lat, lon = [], start, 0, 0
    for i in range(len(v["t"])):
        t, lat, lon = t + v["t"][i], lat + v["lat"][i], lon + v["lon"][i]
        out.append((t, lat / 1e5, lon / 1e5, v["d"][i], strings[v["line"][i]], v.get("run", [None] * (i + 1))[i]))
    return out


def test_replay_chunk_tracks_each_vehicle_across_the_chunk_edges(tmp_path, monkeypatch):
    logger = PollLogger(tmp_path / "logs")
    polls = [T0 + timedelta(seconds=15 * i) for i in range(4 * 25)]  # 15:50 to 16:14:45
    for i, ts in enumerate(polls):
        bus = Vehicle("1843", "83", "Dlhé diely", "bus", 48.1 + i * 1e-4, 17.1, 60 + i, 0, 90)
        logger.log_poll(ts, [bus] if i % 2 == 0 else [bus, Vehicle("7101", "4", None, "tram", 48.2, 17.2, None, 0, None)], 300, None)
        if i % 4 == 0:
            logger.log_sweep(ts, [Vehicle("idsbk:abc", "501", "Senec", "bus", 48.3, 17.4, 30, None, None)], 3, 900, None)
        if ts in (datetime(2026, 11, 13, 16, 1, tzinfo=UTC), datetime(2026, 11, 13, 16, 8, tzinfo=UTC)):
            ev = {"ts": ts, "service_date": ts.date(), "trip": "t1", "line": "83", "dir": "0", "seq": 0, "stop": "s",
                  "scheduled": ts, "actual": ts, "delay_s": 60, "vehicle": "1843", "final": False}
            logger.log_stop_events(ts, [ev])
    # A part left behind by a crash between compaction and deleting the parts: its poll is in the hour file.
    d = tmp_path / "logs" / "vehicles" / "date=2026-11-13"
    hour = pq.read_table(d / "hour=15.parquet")
    pq.write_table(hour.filter(pc.equal(hour["ts"], hour["ts"][-1])), d / "hour=15.part-1.parquet")

    monkeypatch.setattr(mhd.app, "DATA_DIR", tmp_path)
    with TestClient(mhd.app.create_app(poller=Poller(logger=None), start_polling=False)) as c:
        span = c.get("/api/replay").json()
        assert span["hours"] == [int(datetime(2026, 11, 13, h, tzinfo=UTC).timestamp()) for h in (15, 16)]

        t = int(datetime(2026, 11, 13, 16, 3, 20, tzinfo=UTC).timestamp())
        r = c.get(f"/api/replay/{t}")
    body = r.json()
    start = int(datetime(2026, 11, 13, 16, tzinfo=UTC).timestamp())
    assert (body["start"], body["end"]) == (start, start + 600)
    # A past chunk never changes, so the browser may keep it.
    assert body["complete"] is True and r.headers["cache-control"] == "private, max-age=86400"

    by_key = {v["key"]: v for v in body["vehicles"]}
    assert set(by_key) == {"1843", "7101", "idsbk:abc"}
    bus = _decode(by_key["1843"], start, body["strings"])
    # Two minutes either side of the chunk: 15:58:00 to 16:11:45, every poll once.
    assert [s[0] for s in bus] == list(range(start - 120, start + 720, 15))
    i = (8 * 60) // 15  # polls since 15:50 at 15:58
    assert bus[0][1:5] == (round(48.1 + i * 1e-4, 5), 17.1, 60 + i, "83")
    # Running between the trip's first and last recorded stop (16:01 and 16:08), else not.
    run = {s[0] - start: s[5] for s in bus}
    assert (run[45], run[60], run[480], run[495]) == (0, 1, 1, 0)
    assert len(_decode(by_key["7101"], start, body["strings"])) == len(bus) // 2
    assert by_key["7101"]["d"][0] is None and by_key["7101"]["type"] == "tram"
