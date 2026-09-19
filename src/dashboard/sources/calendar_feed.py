"""Upcoming events from one or more iCalendar feeds.

Google Calendar is read through its **secret iCal address** rather than the
Calendar API: Settings -> *your calendar* -> "Secret address in iCal format".
That URL needs no OAuth client, no consent screen and no token refresh, which
matters for a headless container that nobody logs into.  Treat it like a
password -- anyone holding it can read the calendar -- and set it as an app
environment variable, never in the repository.

The same code reads any ICS feed (Apple iCloud, Fastmail, Nextcloud, a sports
schedule), so ``CALENDAR_ICS_URLS`` takes a comma-separated list.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, time, timedelta

import requests

from .. import secrets
from ..charts import bar_chart
from ..config import CalendarFeed, Config, parse_feeds
from .base import Item, Metric, Panel, Source

_SETUP_HINT = (
    "Set CALENDAR_ICS_URLS to your calendar's secret iCal address "
    '(comma-separated; "Label=URL" to name a feed). On a Bottle, store it in '
    "the Secrets app under that name."
)


class CalendarSource(Source):
    key = "calendar"
    title = "Upcoming"

    def collect(self, config: Config) -> Panel:
        try:
            feeds = self._feeds(config)
        except secrets.SecretsUnavailable as exc:
            # The grant is declared but the service did not answer. Say so --
            # showing the "not configured yet" hint would send you looking in
            # the wrong place.
            return self.panel(error=f"secrets service: {exc}",
                              empty_message="Calendar feeds could not be read.")

        if not feeds:
            return self.panel(stub=True, empty_message=_SETUP_HINT)

        now = datetime.now(config.timezone)
        window_end = now + timedelta(days=config.calendar_lookahead_days)

        events: list[dict] = []
        failures: list[str] = []
        for feed in feeds:
            try:
                events.extend(self._fetch(feed, config, now, window_end))
            except Exception as exc:  # one bad feed must not lose the others
                failures.append(f"{feed.label}: {exc}")

        events.sort(key=lambda event: event["sort_key"])

        panel = self.panel(
            subtitle=f"Next {config.calendar_lookahead_days} days",
            items=[self._to_item(event, now) for event in events[:12]],
            empty_message="Nothing scheduled.",
            error="; ".join(failures),
        )

        '''
        if events:
            today = now.date()
            per_day = Counter(event["start"].date() for event in events)
            days = [today + timedelta(days=offset)
                    for offset in range(config.calendar_lookahead_days)]
            panel.chart = bar_chart(
                "calendar-load",
                [day.strftime("%a") for day in days],
                [per_day.get(day, 0) for day in days],
                columns=("Day", "Events"),
            )
            panel.metrics = [
                Metric("Today", str(per_day.get(today, 0)), "events"),
                Metric("This window", str(len(events)), "events"),
            ]
        '''
        return panel

    def _feeds(self, config: Config) -> tuple[CalendarFeed, ...]:
        """Where the feed list comes from, in order of precedence.

        The environment wins so that ``docker run --env-file`` keeps working
        unchanged for local development, and so an operator can override a
        stored secret without editing it.
        """
        if config.calendar_feeds:
            return config.calendar_feeds
        return parse_feeds(secrets.get_secret("CALENDAR_ICS_URLS", config))

    def _fetch(
        self,
        feed: CalendarFeed,
        config: Config,
        start: datetime,
        end: datetime,
    ) -> list[dict]:
        # Imported lazily so a missing optional dependency surfaces as one
        # broken panel rather than an import error that kills generation.
        import icalendar
        import recurring_ical_events

        response = requests.get(
            feed.url,
            timeout=config.http_timeout,
            headers={"User-Agent": "alan-dashboard/0.1"},
        )
        response.raise_for_status()
        calendar = icalendar.Calendar.from_ical(response.content)

        collected = []
        for event in recurring_ical_events.of(calendar).between(start, end):
            raw_start = event.get("DTSTART").dt
            all_day = isinstance(raw_start, date) and not isinstance(raw_start, datetime)
            if all_day:
                moment = datetime.combine(raw_start, time.min, tzinfo=config.timezone)
            else:
                moment = raw_start.astimezone(config.timezone)
            collected.append(
                {
                    "summary": str(event.get("SUMMARY", "(no title)")),
                    "location": str(event.get("LOCATION", "")).strip(),
                    "start": moment,
                    "all_day": all_day,
                    "feed": feed.label,
                    # All-day events sort above timed ones on the same date.
                    "sort_key": (moment.date(), 0 if all_day else 1, moment),
                }
            )
        return collected

    def _to_item(self, event: dict, now: datetime) -> Item:
        start = event["start"]
        day = start.date()
        if day == now.date():
            day_label = "Today"
        elif day == now.date() + timedelta(days=1):
            day_label = "Tomorrow"
        else:
            day_label = start.strftime("%a %-d %b")

        when = day_label if event["all_day"] else f"{day_label} {start.strftime('%-H:%M')}"
        return Item(
            primary=event["summary"],
            secondary=when,
            meta=event["location"] or event["feed"],
            highlight=day == now.date(),
        )
