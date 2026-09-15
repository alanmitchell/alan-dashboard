"""The contract every data source implements.

A source turns "some API somewhere" into one :class:`Panel`.  It may raise --
:mod:`dashboard.generate` catches per source, so one unreachable service
degrades a single card instead of blanking the whole page.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..charts import Chart
from ..config import Config


@dataclass
class Metric:
    """A single headline number: the big readout at the top of a panel."""

    label: str
    value: str
    unit: str = ""
    note: str = ""


@dataclass
class Item:
    """One row in a list panel, e.g. a calendar event."""

    primary: str
    secondary: str = ""
    meta: str = ""
    highlight: bool = False


@dataclass
class Panel:
    key: str
    title: str
    subtitle: str = ""
    metrics: list[Metric] = field(default_factory=list)
    items: list[Item] = field(default_factory=list)
    chart: Chart | None = None
    empty_message: str = "No data yet."
    error: str = ""
    # Set by the placeholder sources so the page is honest about which cards
    # are not yet wired to anything real.
    stub: bool = False

    @property
    def is_empty(self) -> bool:
        return not (self.metrics or self.items or self.chart)


class Source:
    """Base class for data sources.

    Subclasses set ``key``/``title`` and implement :meth:`collect`.
    """

    key: str = ""
    title: str = ""

    def collect(self, config: Config) -> Panel:
        raise NotImplementedError

    def panel(self, **kwargs) -> Panel:
        kwargs.setdefault("key", self.key)
        kwargs.setdefault("title", self.title)
        return Panel(**kwargs)
