"""Registry of data sources.

Order here is the order panels appear on the page.  Adding a source means
writing one module and adding one line below.
"""

from __future__ import annotations

from .activity import ActivitySource
from .base import Item, Metric, Panel, Source
from .calendar_feed import CalendarSource
from .energy import EnergySource
from .home_climate import HomeClimateSource

__all__ = ["Item", "Metric", "Panel", "Source", "all_sources"]


def all_sources() -> list[Source]:
    return [
        CalendarSource(),
        HomeClimateSource(),
        EnergySource(),
        ActivitySource(),
    ]
