"""Palette tokens shared by the CSS and the matplotlib charts.

Values come from the reference data-viz palette unchanged.  Categorical slots
are assigned in fixed order and never cycled; charts here use at most two
series, which keeps them inside the range that validates all-pairs in both
light and dark modes.

Each chart is rendered twice -- once per theme -- because a matplotlib SVG bakes
its colors in and cannot follow ``prefers-color-scheme`` the way CSS can.  The
page shows whichever one matches the viewer.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Theme:
    name: str
    surface: str
    ink: str
    secondary_ink: str
    muted: str
    grid: str
    axis: str
    series: tuple[str, ...]


LIGHT = Theme(
    name="light",
    surface="#fcfcfb",
    ink="#0b0b0b",
    secondary_ink="#52514e",
    muted="#898781",
    grid="#e1e0d9",
    axis="#c3c2b7",
    series=("#2a78d6", "#eb6834", "#1baf7a"),
)

DARK = Theme(
    name="dark",
    surface="#1a1a19",
    ink="#ffffff",
    secondary_ink="#c3c2b7",
    muted="#898781",
    grid="#2c2c2a",
    axis="#383835",
    series=("#3987e5", "#d95926", "#199e70"),
)

THEMES: tuple[Theme, ...] = (LIGHT, DARK)
