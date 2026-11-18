import logging

from fastapi.testclient import TestClient

from mhd import accounts
from mhd.app import create_app
from mhd.poller import Poller


def test_large_account_requests_are_refused_before_forwarding():
    """An upload must not be buffered into memory: the replica also runs the map and poller."""
    with TestClient(create_app(poller=Poller(logger=None), start_polling=False)) as c:
        big = b"{" + b" " * (accounts.MAX_BODY + 1) + b"}"
        assert c.post("/api/auth/profile/favorites", content=big).status_code == 413

        def chunks():  # no Content-Length
            for _ in range(3):
                yield b" " * accounts.MAX_BODY

        assert c.post("/api/auth/profile/favorites", content=chunks()).status_code == 413


def test_email_link_tokens_stay_out_of_the_access_log():
    f = accounts._RedactTokens()

    def record(path):
        return logging.LogRecord("uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d',
                                 ("1.2.3.4:5", "GET", path, "1.1", 200), None)

    assert not f.filter(record("/api/auth/reset-password/SECRET?callbackURL=%2Fucet"))
    assert not f.filter(record("/api/auth/verify-email?token=SECRET"))
    r = record("/ucet?token=SECRET&x=1")
    assert f.filter(r) and "SECRET" not in r.getMessage() and "x=1" in r.getMessage()
    r = record("/api/live")
    assert f.filter(r) and "1.2.3.4" not in r.getMessage() and "/api/live" in r.getMessage()
