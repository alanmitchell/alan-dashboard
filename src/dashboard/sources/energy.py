"""Household electricity use.

PLACEHOLDER -- returns sample data.

To make it real, replace :meth:`_hourly_kwh` with a call to your meter, inverter
or utility API (Home Assistant's energy statistics, a Shelly/Emporia endpoint,
an Enphase or SolarEdge API...).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from ..charts import bar_chart
from ..config import Config
from ._sample import daily_curve
from .base import Metric, Panel, Source


class EnergySource(Source):
    key = "energy"
    title = "Electricity"

    def collect(self, config: Config) -> Panel:
        now = datetime.now(config.timezone)
        hourly = self._hourly_kwh(config)
        labels = [(now - timedelta(hours=23 - offset)).strftime("%-H")
                  for offset in range(24)]

        total = sum(hourly)
        peak_index = max(range(len(hourly)), key=hourly.__getitem__)

        return self.panel(
            subtitle="Last 24 hours",
            stub=True,
            metrics=[
                Metric("Used", f"{total:.1f}", "kWh"),
                Metric("Now", f"{hourly[-1]:.2f}", "kWh/h"),
                Metric("Peak", f"{labels[peak_index]}:00", note=f"{hourly[peak_index]:.2f} kWh"),
            ],
            chart=bar_chart(
                "energy",
                labels,
                hourly,
                columns=("Hour", "kWh"),
            ),
        )

    def _hourly_kwh(self, config: Config) -> list[float]:
        # TODO: replace with real meter readings.
        return [max(0.05, round(value, 2))
                for value in daily_curve("energy", base=0.65, swing=0.45,
                                         peak_hour=19, noise=0.12)]
