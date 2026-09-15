"""Configuration, read entirely from environment variables.

Cloud in a Bottle injects ``BOTTLE_*`` variables into the container; everything
else is set in the app's environment on the Bottle dashboard.  Nothing here
reads a config file, so there is no state to keep in sync with the manifest.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def _str(name: str, default: str = "") -> str:
    value = os.environ.get(name, "").strip()
    return value or default


def _int(name: str, default: int) -> int:
    raw = _str(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    raw = _str(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class CalendarFeed:
    """One iCalendar feed to display."""

    label: str
    url: str


def _parse_feeds(raw: str) -> tuple[CalendarFeed, ...]:
    """Parse ``CALENDAR_ICS_URLS`` into feeds.

    Entries are comma-separated and may be either a bare URL or ``Label=URL``.
    Only the first ``=`` splits, and only when the left-hand side looks like a
    label rather than part of a URL -- ICS URLs are full of query parameters.
    """
    feeds: list[CalendarFeed] = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        label, _, rest = entry.partition("=")
        if rest and not any(char in label for char in ":/?&"):
            feeds.append(CalendarFeed(label=label.strip(), url=rest.strip()))
        else:
            # Numbered by feed, so a stray comma does not skip a number.
            feeds.append(CalendarFeed(label=f"Calendar {len(feeds) + 1}", url=entry))
    return tuple(feeds)


def _output_base() -> Path:
    """Where the rendered site goes.

    Generated HTML is reproducible from the sources, so it belongs in the
    platform's *temp* tier rather than the backed-up permanent tier.  Fall back
    through the permanent tier to a local directory for development.
    """
    for name in ("DASHBOARD_OUTPUT_DIR", "BOTTLE_APP_TEMP_DIR", "BOTTLE_APP_DATA_DIR"):
        value = _str(name)
        if value:
            return Path(value)
    return Path("var")


@dataclass(frozen=True)
class Config:
    title: str
    subtitle: str
    tz_name: str
    timezone: ZoneInfo
    output_dir: Path
    data_dir: Path
    refresh_seconds: int
    http_timeout: float
    calendar_feeds: tuple[CalendarFeed, ...]
    calendar_lookahead_days: int
    host: str
    port: int

    @classmethod
    def from_env(cls) -> "Config":
        tz_name = _str("TZ", "UTC")
        try:
            timezone = ZoneInfo(tz_name)
        except (ZoneInfoNotFoundError, ValueError):
            tz_name, timezone = "UTC", ZoneInfo("UTC")

        return cls(
            title=_str("DASHBOARD_TITLE", "Home Dashboard"),
            subtitle=_str("DASHBOARD_SUBTITLE"),
            tz_name=tz_name,
            timezone=timezone,
            output_dir=_output_base() / "site",
            data_dir=Path(_str("BOTTLE_APP_DATA_DIR", "var/data")),
            # The page meta-refreshes a little after cron regenerates it, so a
            # wall display picks up new data without anyone touching it.
            refresh_seconds=_int("DASHBOARD_REFRESH_SECONDS", 1860),
            http_timeout=_float("DASHBOARD_HTTP_TIMEOUT", 15.0),
            calendar_feeds=_parse_feeds(_str("CALENDAR_ICS_URLS")),
            calendar_lookahead_days=_int("CALENDAR_LOOKAHEAD_DAYS", 7),
            host=_str("DASHBOARD_HOST", "0.0.0.0"),
            port=_int("PORT", 8080),
        )

    @property
    def index_path(self) -> Path:
        return self.output_dir / "index.html"
