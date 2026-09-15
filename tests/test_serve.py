"""The server answers the router, so its status codes are the contract."""

from __future__ import annotations

import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from dashboard.serve import Handler


@pytest.fixture
def server(config):
    Handler.config = config
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def _get(url):
    try:
        response = urllib.request.urlopen(url, timeout=5)
        return response.status, response.read(), dict(response.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers)


def test_health_check_is_independent_of_the_generated_page(server, config):
    """A failed rebuild must not read as an unhealthy container."""
    assert not config.index_path.exists()
    status, body, _ = _get(f"{server}/healthz")
    assert (status, body) == (200, b"ok")


def test_missing_page_returns_a_self_refreshing_placeholder(server):
    status, body, headers = _get(f"{server}/")
    assert status == 503
    assert b"Building the dashboard" in body
    assert headers["Retry-After"] == "10"


def test_generated_page_is_served(server, config):
    config.index_path.parent.mkdir(parents=True, exist_ok=True)
    config.index_path.write_text("<!doctype html><title>hi</title>", encoding="utf-8")

    status, body, headers = _get(f"{server}/")
    assert status == 200
    assert b"<title>hi</title>" in body
    assert headers["Content-Type"] == "text/html; charset=utf-8"
    # The page is rewritten every half hour; a cached copy would go stale.
    assert "no-store" in headers["Cache-Control"]
    assert headers["X-Content-Type-Options"] == "nosniff"


def test_unknown_paths_are_not_found(server):
    status, _, _ = _get(f"{server}/../etc/passwd")
    assert status == 404


def test_trailing_slash_and_query_still_reach_the_page(server, config):
    config.index_path.parent.mkdir(parents=True, exist_ok=True)
    config.index_path.write_text("ok", encoding="utf-8")
    for path in ("/", "/?v=1"):
        status, body, _ = _get(f"{server}{path}")
        assert (status, body) == (200, b"ok")
