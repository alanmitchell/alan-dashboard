"""Config is parsed from the environment, so the parsing is the whole surface."""

from __future__ import annotations

from pathlib import Path

from dashboard.config import Config, parse_feeds


def test_bare_url_gets_a_generated_label():
    feeds = parse_feeds("https://example.com/basic.ics")
    assert [(f.label, f.url) for f in feeds] == [
        ("Calendar 1", "https://example.com/basic.ics")
    ]


def test_explicit_label_is_used():
    (feed,) = parse_feeds("Home=https://example.com/home.ics")
    assert (feed.label, feed.url) == ("Home", "https://example.com/home.ics")


def test_query_string_equals_is_not_mistaken_for_a_label():
    """The case that makes naive `split("=")` wrong: Google's iCal addresses
    are full of `=` in the path and query."""
    url = "https://calendar.google.com/calendar/ical/abc%3D%3D/private-x/basic.ics?key=v&b=2"
    (feed,) = parse_feeds(url)
    assert feed.url == url
    assert feed.label == "Calendar 1"


def test_multiple_feeds_and_blank_entries():
    feeds = parse_feeds(" A=https://a.example/a.ics , ,https://b.example/b.ics ")
    assert [(f.label, f.url) for f in feeds] == [
        ("A", "https://a.example/a.ics"),
        ("Calendar 2", "https://b.example/b.ics"),
    ]


def test_no_feeds_configured():
    assert parse_feeds("") == ()


def test_output_dir_prefers_temp_tier_over_permanent(clean_env):
    """Generated HTML is reproducible, so it belongs in the scratch tier."""
    clean_env.setenv("BOTTLE_APP_DATA_DIR", "/data/app_data/x")
    clean_env.setenv("BOTTLE_APP_TEMP_DIR", "/data/app_temp_data/x")
    assert Config.from_env().index_path == Path("/data/app_temp_data/x/site/index.html")


def test_output_dir_falls_back_to_permanent_tier(clean_env):
    clean_env.setenv("BOTTLE_APP_DATA_DIR", "/data/app_data/x")
    assert Config.from_env().output_dir == Path("/data/app_data/x/site")


def test_output_dir_falls_back_to_local_dir(clean_env):
    assert Config.from_env().output_dir == Path("var/site")


def test_explicit_override_wins_over_platform(clean_env):
    clean_env.setenv("BOTTLE_APP_TEMP_DIR", "/data/app_temp_data/x")
    clean_env.setenv("DASHBOARD_OUTPUT_DIR", "/tmp/elsewhere")
    assert Config.from_env().output_dir == Path("/tmp/elsewhere/site")


def test_unknown_timezone_falls_back_to_utc(clean_env):
    """A typo'd TZ must not take the whole dashboard down."""
    clean_env.setenv("TZ", "Mars/Olympus_Mons")
    config = Config.from_env()
    assert config.tz_name == "UTC"


def test_real_timezone_is_honoured(clean_env):
    clean_env.setenv("TZ", "America/Anchorage")
    assert Config.from_env().tz_name == "America/Anchorage"


def test_non_numeric_ints_fall_back_to_defaults(clean_env):
    clean_env.setenv("CALENDAR_LOOKAHEAD_DAYS", "soon")
    clean_env.setenv("PORT", "")
    config = Config.from_env()
    assert config.calendar_lookahead_days == 7
    assert config.port == 8080
