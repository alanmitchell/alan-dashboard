"""Indoor/outdoor climate.

PLACEHOLDER -- returns sample data.

To make it real, replace :meth:`_readings`.  For Home Assistant that is a GET to
``{HASS_URL}/api/history/period/{start}?filter_entity_id=sensor.indoor_temp``
with an ``Authorization: Bearer <long-lived token>`` header; read both from the
environment via :mod:`dashboard.config`.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from ..charts import line_chart
from ..config import Config
from ._sample import daily_curve
from .base import Metric, Panel, Source


class HomeClimateSource(Source):
    key = "climate"
    title = "Climate"

    def collect(self, config: Config) -> Panel:
        now = datetime.now(config.timezone)
        indoor, outdoor = self._readings(config)

        hours = [(now - timedelta(hours=23 - offset)).strftime("%-H")
                 for offset in range(24)]

        return self.panel(
            subtitle="Last 24 hours",
            stub=True,
            metrics=[
                Metric("Indoor", f"{indoor[-1]:.1f}", "°C"),
                Metric("Outdoor", f"{outdoor[-1]:.1f}", "°C"),
                Metric("Difference", f"{indoor[-1] - outdoor[-1]:+.1f}", "°C"),
            ],
            chart=line_chart(
                "climate",
                hours,
                [("Indoor", indoor), ("Outdoor", outdoor)],
                unit="°",
                columns=("Hour", "Indoor / Outdoor"),
            ),
        )

    def _readings(self, config: Config) -> tuple[list[float], list[float]]:
        # TODO: replace with a real query against your sensor history.
        indoor = daily_curve("indoor", base=21.0, swing=1.2, peak_hour=17, noise=0.2)
        outdoor = daily_curve("outdoor", base=11.0, swing=6.0, peak_hour=15, noise=0.8)
        return indoor, outdoor
