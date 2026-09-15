"""Calendar parsing, with the network stubbed out.

Fixtures are built relative to "now" so the tests do not rot, and assertions
avoid wall-clock-dependent wording.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from dashboard.sources import calendar_feed
from dashboard.sources.calendar_feed import CalendarSource


class _FakeResponse:
    def __init__(self, body: bytes, status: int = 200):
        self.content = body
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _stub_feed(monkeypatch, body: bytes, status: int = 200) -> None:
    def fake_get(url, **kwargs):
        assert "timeout" in kwargs, "every outbound call must carry a timeout"
        return _FakeResponse(body, status)

    monkeypatch.setattr(calendar_feed.requests, "get", fake_get)


def _utc(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _calendar(*events: str) -> bytes:
    body = "\r\n".join(
        ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//test//EN", *events, "END:VCALENDAR"]
    )
    return body.encode("utf-8")


def _event(uid: str, summary: str, start: str, end: str, *extra: str) -> str:
    return "\r\n".join(
        [
            "BEGIN:VEVENT",
            f"UID:{uid}",
            "DTSTAMP:20260101T000000Z",
            f"DTSTART:{start}",
            f"DTEND:{end}",
            f"SUMMARY:{summary}",
            *extra,
            "END:VEVENT",
        ]
    )


@pytest.fixture
def feeds(clean_env):
    clean_env.setenv("CALENDAR_ICS_URLS", "Home=https://example.invalid/home.ics")


def _collect(config):
    return CalendarSource().collect(config)


def test_without_feeds_the_panel_explains_the_setup(config):
    panel = _collect(config)
    assert panel.stub is True
    assert "CALENDAR_ICS_URLS" in panel.empty_message
    assert panel.error == ""


def test_upcoming_event_is_listed(monkeypatch, feeds, config):
    now = datetime.now(timezone.utc)
    _stub_feed(
        monkeypatch,
        _calendar(
            _event("1", "Dentist", _utc(now + timedelta(hours=2)),
                   _utc(now + timedelta(hours=3)), "LOCATION:Clinic")
        ),
    )
    panel = _collect(config)
    assert panel.error == ""
    assert [item.primary for item in panel.items] == ["Dentist"]
    assert panel.items[0].meta == "Clinic"


def test_finished_event_is_excluded(monkeypatch, feeds, config):
    now = datetime.now(timezone.utc)
    _stub_feed(
        monkeypatch,
        _calendar(
            _event("1", "Already happened", _utc(now - timedelta(hours=3)),
                   _utc(now - timedelta(hours=2)))
        ),
    )
    assert _collect(config).items == []


def test_event_beyond_the_window_is_excluded(monkeypatch, feeds, config):
    now = datetime.now(timezone.utc)
    _stub_feed(
        monkeypatch,
        _calendar(
            _event("1", "Next month", _utc(now + timedelta(days=30)),
                   _utc(now + timedelta(days=30, hours=1)))
        ),
    )
    assert _collect(config).items == []


def test_recurring_event_expands_to_every_occurrence(monkeypatch, feeds, config):
    """A weekly standup must appear on each occurrence, not only its first."""
    start = datetime.now(timezone.utc) + timedelta(hours=1)
    _stub_feed(
        monkeypatch,
        _calendar(
            _event("1", "Standup", _utc(start), _utc(start + timedelta(minutes=30)),
                   "RRULE:FREQ=DAILY;COUNT=5")
        ),
    )
    panel = _collect(config)
    assert [item.primary for item in panel.items] == ["Standup"] * 5


def test_all_day_event_sorts_above_timed_events_that_day(monkeypatch, feeds, config):
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).date()
    timed_start = datetime.combine(
        tomorrow, datetime.min.time(), tzinfo=timezone.utc
    ) + timedelta(hours=14)
    _stub_feed(
        monkeypatch,
        _calendar(
            _event("1", "Timed thing", _utc(timed_start),
                   _utc(timed_start + timedelta(hours=1))),
            "\r\n".join(
                [
                    "BEGIN:VEVENT",
                    "UID:2",
                    "DTSTAMP:20260101T000000Z",
                    f"DTSTART;VALUE=DATE:{tomorrow:%Y%m%d}",
                    f"DTEND;VALUE=DATE:{tomorrow + timedelta(days=1):%Y%m%d}",
                    "SUMMARY:All day thing",
                    "END:VEVENT",
                ]
            ),
        ),
    )
    summaries = [item.primary for item in _collect(config).items]
    assert summaries.index("All day thing") < summaries.index("Timed thing")


def test_times_are_shown_in_the_configured_timezone(monkeypatch, clean_env, tmp_path):
    from dashboard.config import Config

    clean_env.setenv("TZ", "America/Anchorage")
    clean_env.setenv("DASHBOARD_OUTPUT_DIR", str(tmp_path))
    clean_env.setenv("CALENDAR_ICS_URLS", "https://example.invalid/home.ics")
    config = Config.from_env()

    # 17:00 UTC is 09:00 in Anchorage (AKDT, UTC-8) during September.
    target = (datetime.now(timezone.utc) + timedelta(days=2)).replace(
        hour=17, minute=0, second=0, microsecond=0
    )
    _stub_feed(
        monkeypatch,
        _calendar(_event("1", "Standup", _utc(target), _utc(target + timedelta(minutes=30)))),
    )
    (item,) = _collect(config).items
    assert item.secondary.endswith("9:00")


def test_a_broken_feed_reports_instead_of_raising(monkeypatch, feeds, config):
    def explode(url, **kwargs):
        raise OSError("name or service not known")

    monkeypatch.setattr(calendar_feed.requests, "get", explode)
    panel = _collect(config)
    assert "name or service not known" in panel.error
    assert panel.items == []


def test_one_broken_feed_does_not_lose_the_other(monkeypatch, clean_env, tmp_path):
    from dashboard.config import Config

    clean_env.setenv("TZ", "UTC")
    clean_env.setenv("DASHBOARD_OUTPUT_DIR", str(tmp_path))
    clean_env.setenv(
        "CALENDAR_ICS_URLS",
        "Good=https://good.invalid/a.ics,Bad=https://bad.invalid/b.ics",
    )
    config = Config.from_env()

    now = datetime.now(timezone.utc)
    good = _calendar(
        _event("1", "Survivor", _utc(now + timedelta(hours=2)),
               _utc(now + timedelta(hours=3)))
    )

    def selective_get(url, **kwargs):
        if "bad.invalid" in url:
            raise OSError("unreachable")
        return _FakeResponse(good)

    monkeypatch.setattr(calendar_feed.requests, "get", selective_get)
    panel = _collect(config)
    assert [item.primary for item in panel.items] == ["Survivor"]
    assert "Bad: unreachable" in panel.error


def test_http_error_is_surfaced(monkeypatch, feeds, config):
    _stub_feed(monkeypatch, b"", status=404)
    panel = _collect(config)
    assert "404" in panel.error


# --- where the feed list comes from ------------------------------------------


@pytest.fixture(autouse=True)
def _clear_secret_cache():
    from dashboard import secrets

    secrets.reset_cache()
    yield
    secrets.reset_cache()


def test_environment_wins_over_the_secrets_service(monkeypatch, feeds, config):
    """Local --env-file development must not be overridden by a stored secret."""
    from dashboard import secrets

    def should_not_be_called(*args, **kwargs):  # pragma: no cover
        raise AssertionError("secrets service consulted despite an env override")

    monkeypatch.setattr(secrets, "get_secret", should_not_be_called)
    now = datetime.now(timezone.utc)
    _stub_feed(
        monkeypatch,
        _calendar(_event("1", "From env", _utc(now + timedelta(hours=1)),
                         _utc(now + timedelta(hours=2)))),
    )
    assert [item.primary for item in _collect(config).items] == ["From env"]


def test_secrets_service_supplies_feeds_when_env_is_unset(monkeypatch, config):
    from dashboard import secrets

    monkeypatch.setattr(
        secrets, "get_secret",
        lambda key, cfg: "Stored=https://example.invalid/home.ics",
    )
    now = datetime.now(timezone.utc)
    _stub_feed(
        monkeypatch,
        _calendar(_event("1", "From secrets", _utc(now + timedelta(hours=1)),
                         _utc(now + timedelta(hours=2)))),
    )
    panel = _collect(config)
    assert [item.primary for item in panel.items] == ["From secrets"]
    assert panel.error == ""


def test_unreachable_secrets_service_is_reported_not_disguised(monkeypatch, config):
    """Showing the setup hint here would send you looking in the wrong place."""
    from dashboard import secrets

    def explode(key, cfg):
        raise secrets.SecretsUnavailable("connection refused")

    monkeypatch.setattr(secrets, "get_secret", explode)
    panel = _collect(config)
    assert "secrets service" in panel.error
    assert panel.stub is False


def test_nothing_configured_anywhere_shows_the_setup_hint(monkeypatch, config):
    from dashboard import secrets

    monkeypatch.setattr(secrets, "get_secret", lambda key, cfg: "")
    panel = _collect(config)
    assert panel.stub is True
    assert "Secrets app" in panel.empty_message
    assert panel.error == ""
