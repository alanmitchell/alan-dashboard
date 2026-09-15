"""Configuration, resolved from three places in a fixed order.

Cloud in a Bottle has no mechanism for setting environment variables on an
installed app, so settings that must be changeable after deployment live in a
TOML file in the persistent data tier::

    $BOTTLE_APP_DATA_DIR/config.toml

Precedence is **environment variable, then config file, then built-in
default**. The environment winning keeps ``docker run --env-file`` development
working unchanged and lets an operator override a stored value without editing
it -- the same rule :mod:`dashboard.secrets` uses.

The file is re-read on every generate run, so an edit takes effect on the next
cron tick with no restart and no rebuild.

**Secrets do not belong here.** This tier is backed up, and a credential in a
backup is a credential in more places than you think. Calendar URLs come from
the Secrets app; see :mod:`dashboard.secrets`.
"""

from __future__ import annotations

import os
import time
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

CONFIG_FILENAME = "config.toml"

# Every key the file may contain, mapped to the variable that overrides it.
# Anything else in the file is a typo worth reporting rather than ignoring.
FILE_KEYS = {
    "title": "DASHBOARD_TITLE",
    "subtitle": "DASHBOARD_SUBTITLE",
    "timezone": "TZ",
    "refresh_seconds": "DASHBOARD_REFRESH_SECONDS",
    "calendar_lookahead_days": "CALENDAR_LOOKAHEAD_DAYS",
    "http_timeout": "DASHBOARD_HTTP_TIMEOUT",
}


def _data_dir() -> Path:
    return Path(os.environ.get("BOTTLE_APP_DATA_DIR", "").strip() or "var/data")


def config_file_path() -> Path:
    override = os.environ.get("DASHBOARD_CONFIG_FILE", "").strip()
    return Path(override) if override else _data_dir() / CONFIG_FILENAME


def _load_file(path: Path) -> tuple[dict, list[str]]:
    """Read the config file. A broken file is reported, never fatal.

    Raising here would stop the page regenerating entirely; a visible warning
    on a page that still renders is far easier to act on.
    """
    warnings: list[str] = []
    try:
        with path.open("rb") as handle:
            values = tomllib.load(handle)
    except FileNotFoundError:
        return {}, warnings
    except tomllib.TOMLDecodeError as exc:
        return {}, [f"{path} is not valid TOML ({exc}); using defaults."]
    except OSError as exc:
        return {}, [f"{path} could not be read ({exc}); using defaults."]

    if not isinstance(values, dict):  # pragma: no cover - tomllib always maps
        return {}, [f"{path} must contain a table of settings; using defaults."]

    for key in sorted(set(values) - set(FILE_KEYS)):
        warnings.append(f"Unknown setting {key!r} in {path.name} (ignored).")
    return values, warnings


class _Resolver:
    """Environment, then file, then default."""

    def __init__(self, values: dict, warnings: list[str], source: str):
        self._values = values
        self._source = source
        self.warnings = warnings

    def _reject(self, key: str, expected: str) -> None:
        self.warnings.append(
            f"Setting {key!r} in {self._source} must be {expected}; using the default."
        )

    def text(self, key: str, default: str = "") -> str:
        raw = os.environ.get(FILE_KEYS[key], "").strip()
        if raw:
            return raw
        value = self._values.get(key)
        if value is None:
            return default
        if not isinstance(value, str):
            self._reject(key, "text")
            return default
        return value.strip() or default

    def integer(self, key: str, default: int) -> int:
        raw = os.environ.get(FILE_KEYS[key], "").strip()
        if raw:
            try:
                return int(raw)
            except ValueError:
                return default
        value = self._values.get(key)
        if value is None:
            return default
        # bool is an int subclass; `refresh_seconds = true` is a mistake.
        if not isinstance(value, int) or isinstance(value, bool):
            self._reject(key, "a whole number")
            return default
        return value

    def decimal(self, key: str, default: float) -> float:
        raw = os.environ.get(FILE_KEYS[key], "").strip()
        if raw:
            try:
                return float(raw)
            except ValueError:
                return default
        value = self._values.get(key)
        if value is None:
            return default
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            self._reject(key, "a number")
            return default
        return float(value)


@dataclass(frozen=True)
class CalendarFeed:
    """One iCalendar feed to display."""

    label: str
    url: str


def parse_feeds(raw: str) -> tuple[CalendarFeed, ...]:
    """Parse a ``CALENDAR_ICS_URLS`` value into feeds.

    The value may come from the environment or from the secrets service; see
    :mod:`dashboard.secrets` for which wins.

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
    platform's *temp* tier rather than the backed-up permanent tier. Fall back
    through the permanent tier to a local directory for development.

    Not settable from the config file: the server resolves it once at startup,
    so changing it would need a restart anyway.
    """
    for name in ("DASHBOARD_OUTPUT_DIR", "BOTTLE_APP_TEMP_DIR", "BOTTLE_APP_DATA_DIR"):
        value = os.environ.get(name, "").strip()
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
    # Parsed from the environment only. Empty here does not mean "no
    # calendar": the secrets service is consulted at collect time. Note that no
    # credential is stored on this object -- it lands in tracebacks and reprs.
    calendar_feeds: tuple[CalendarFeed, ...]
    calendar_lookahead_days: int
    host: str
    port: int
    # Problems with the config file, shown on the page so a typo is visible
    # rather than silently ignored.
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_env(cls) -> "Config":
        path = config_file_path()
        values, warnings = _load_file(path)
        settings = _Resolver(values, warnings, path.name)

        tz_name = settings.text("timezone", "UTC")
        try:
            timezone = ZoneInfo(tz_name)
        except (ZoneInfoNotFoundError, ValueError):
            settings.warnings.append(
                f"Unknown timezone {tz_name!r}; falling back to UTC. "
                "Use an IANA name such as America/Anchorage."
            )
            tz_name, timezone = "UTC", ZoneInfo("UTC")

        def _env(name: str, default: str = "") -> str:
            return os.environ.get(name, "").strip() or default

        def _env_int(name: str, default: int) -> int:
            try:
                return int(_env(name) or default)
            except ValueError:
                return default

        return cls(
            title=settings.text("title", "Home Dashboard"),
            subtitle=settings.text("subtitle"),
            tz_name=tz_name,
            timezone=timezone,
            output_dir=_output_base() / "site",
            data_dir=_data_dir(),
            # The page meta-refreshes a little after cron regenerates it, so a
            # wall display picks up new data without anyone touching it.
            refresh_seconds=settings.integer("refresh_seconds", 1860),
            http_timeout=settings.decimal("http_timeout", 15.0),
            calendar_feeds=parse_feeds(_env("CALENDAR_ICS_URLS")),
            calendar_lookahead_days=settings.integer("calendar_lookahead_days", 7),
            host=_env("DASHBOARD_HOST", "0.0.0.0"),
            port=_env_int("PORT", 8080),
            warnings=tuple(settings.warnings),
        )

    @property
    def index_path(self) -> Path:
        return self.output_dir / "index.html"


def apply_process_timezone(config: Config) -> None:
    """Align log timestamps with the timezone shown on the page.

    The page formats its times with :mod:`zoneinfo`, but :mod:`logging` uses
    libc, which reads only the ``TZ`` environment variable. When the timezone
    comes from the config file rather than the environment those two disagree,
    and `bottle logs` prints UTC beside a page that says Anchorage.
    """
    os.environ["TZ"] = config.tz_name
    if hasattr(time, "tzset"):  # Unix only; always true in the container
        time.tzset()
