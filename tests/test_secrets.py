"""The secrets client. The service's reply shape is not documented, so the
parsing is deliberately forgiving about the envelope and strict about the rest.
"""

from __future__ import annotations

import pytest

from dashboard import secrets
from dashboard.secrets import SecretsUnavailable


@pytest.fixture(autouse=True)
def _clear_cache():
    secrets.reset_cache()
    yield
    secrets.reset_cache()


@pytest.fixture
def on_a_bottle(clean_env):
    clean_env.setenv("BOTTLE_ROUTER_URL", "https://router.invalid/")
    clean_env.setenv("BOTTLE_APP_TOKEN", "tok-123")
    return clean_env


class _Reply:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def _stub_post(monkeypatch, payload, status=200, calls=None):
    def fake_post(url, **kwargs):
        if calls is not None:
            calls.append((url, kwargs))
        return _Reply(payload, status)

    monkeypatch.setattr(secrets.requests, "post", fake_post)


def test_absent_service_is_not_an_error(config, clean_env):
    """Plain `docker run` has no router; that means "use the env var", not "fail"."""
    assert secrets.available() is False
    assert secrets.get_secret("CALENDAR_ICS_URLS", config) == ""


def test_reads_a_flat_reply(monkeypatch, on_a_bottle, config):
    _stub_post(monkeypatch, {"CALENDAR_ICS_URLS": "https://cal.invalid/a.ics"})
    assert secrets.get_secret("CALENDAR_ICS_URLS", config) == "https://cal.invalid/a.ics"


@pytest.mark.parametrize("envelope", ["secrets", "values", "data", "result"])
def test_reads_a_wrapped_reply(monkeypatch, on_a_bottle, config, envelope):
    _stub_post(monkeypatch, {envelope: {"K": "v"}})
    assert secrets.get_secret("K", config) == "v"


def test_request_is_authenticated_and_scoped(monkeypatch, on_a_bottle, config):
    calls = []
    _stub_post(monkeypatch, {"K": "v"}, calls=calls)
    secrets.get_secret("K", config)

    (url, kwargs), = calls
    assert url == "https://router.invalid/api/services/v2/call/secrets/get"
    assert kwargs["headers"]["Authorization"] == "Bearer tok-123"
    assert kwargs["json"] == {"keys": ["K"]}
    assert kwargs["timeout"] == config.http_timeout


def test_value_is_cached_across_calls(monkeypatch, on_a_bottle, config):
    calls = []
    _stub_post(monkeypatch, {"K": "v"}, calls=calls)
    assert secrets.get_secret("K", config) == "v"
    assert secrets.get_secret("K", config) == "v"
    assert len(calls) == 1


def test_unset_key_reads_as_empty(monkeypatch, on_a_bottle, config):
    """The owner simply has not stored it yet -- the panel should say so."""
    _stub_post(monkeypatch, {"secrets": {}})
    assert secrets.get_secret("K", config) == ""


def test_null_value_reads_as_empty(monkeypatch, on_a_bottle, config):
    _stub_post(monkeypatch, {"K": None})
    assert secrets.get_secret("K", config) == ""


def test_transport_failure_raises(monkeypatch, on_a_bottle, config):
    def explode(url, **kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr(secrets.requests, "post", explode)
    with pytest.raises(SecretsUnavailable, match="connection refused"):
        secrets.get_secret("K", config)


def test_http_error_raises(monkeypatch, on_a_bottle, config):
    _stub_post(monkeypatch, {}, status=403)
    with pytest.raises(SecretsUnavailable):
        secrets.get_secret("K", config)


def test_unrecognisable_reply_raises_rather_than_reading_as_unset(
    monkeypatch, on_a_bottle, config
):
    """Misreading a reply as "not set" would send you hunting in the wrong place."""
    _stub_post(monkeypatch, ["not", "a", "mapping"])
    with pytest.raises(SecretsUnavailable):
        secrets.get_secret("K", config)


def test_non_string_value_raises(monkeypatch, on_a_bottle, config):
    _stub_post(monkeypatch, {"K": {"nested": "object"}})
    with pytest.raises(SecretsUnavailable):
        secrets.get_secret("K", config)


def test_failure_message_never_leaks_the_token(monkeypatch, on_a_bottle, config):
    def explode(url, **kwargs):
        raise OSError("boom")

    monkeypatch.setattr(secrets.requests, "post", explode)
    with pytest.raises(SecretsUnavailable) as caught:
        secrets.get_secret("K", config)
    assert "tok-123" not in str(caught.value)
