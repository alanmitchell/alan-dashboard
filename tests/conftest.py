from __future__ import annotations

import pytest

from dashboard.config import Config

# Anything that would leak the developer's own settings into a test.
_MANAGED_PREFIXES = ("DASHBOARD_", "BOTTLE_", "CALENDAR_")
_MANAGED_EXACT = ("TZ", "PORT")


@pytest.fixture
def clean_env(monkeypatch):
    """Strip every variable the app reads, so tests see documented defaults."""
    import os

    for key in list(os.environ):
        if key.startswith(_MANAGED_PREFIXES) or key in _MANAGED_EXACT:
            monkeypatch.delenv(key, raising=False)
    return monkeypatch


@pytest.fixture
def config(clean_env, tmp_path) -> Config:
    clean_env.setenv("TZ", "UTC")
    clean_env.setenv("DASHBOARD_OUTPUT_DIR", str(tmp_path))
    return Config.from_env()
