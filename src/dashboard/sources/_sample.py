"""Deterministic sample data for the not-yet-wired panels.

Seeded from the day so the page looks alive across runs without becoming
jittery within a day.  Delete this module once every source is real.
"""

from __future__ import annotations

import math
import random
from datetime import date


def generator(name: str, day: date | None = None) -> random.Random:
    day = day or date.today()
    return random.Random(f"{name}:{day.isoformat()}")


def daily_curve(
    name: str,
    hours: int = 24,
    *,
    base: float,
    swing: float,
    peak_hour: int = 15,
    noise: float = 0.0,
) -> list[float]:
    """A smooth 24h cycle peaking at ``peak_hour`` -- the shape most home
    measurements (temperature, load) actually have."""
    rng = generator(name)
    values = []
    for hour in range(hours):
        phase = (hour - peak_hour) / hours * 2 * math.pi
        value = base + swing * math.cos(phase)
        if noise:
            value += rng.uniform(-noise, noise)
        values.append(round(value, 1))
    return values
