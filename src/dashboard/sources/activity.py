"""Personal activity over the past week.

PLACEHOLDER -- returns sample data.

To make it real, replace :meth:`_daily_steps` with a call to whatever holds your
activity history (Fitbit, Withings, Garmin Connect, Strava, Apple Health export).
Most of these need OAuth; store the refresh token under ``BOTTLE_APP_DATA_DIR``
so it survives container rebuilds.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from ..charts import bar_chart
from ..config import Config
from ._sample import generator
from .base import Metric, Panel, Source

_GOAL = 8000


class ActivitySource(Source):
    key = "activity"
    title = "Activity"

    def collect(self, config: Config) -> Panel:
        now = datetime.now(config.timezone)
        steps = self._daily_steps(config)
        labels = [(now - timedelta(days=6 - offset)).strftime("%a")
                  for offset in range(7)]

        met_goal = sum(1 for value in steps if value >= _GOAL)

        return self.panel(
            subtitle="Last 7 days",
            stub=True,
            metrics=[
                Metric("Today", f"{steps[-1]:,}", "steps"),
                Metric("Daily average", f"{round(sum(steps) / len(steps)):,}", "steps"),
                Metric("Goal met", f"{met_goal}/7", note=f"target {_GOAL:,}"),
            ],
            chart=bar_chart(
                "activity",
                labels,
                [float(value) for value in steps],
                columns=("Day", "Steps"),
            ),
        )

    def _daily_steps(self, config: Config) -> list[int]:
        # TODO: replace with your real activity history.
        rng = generator("activity")
        return [rng.randint(3200, 14000) for _ in range(7)]
