"""The settings file in the persistent data tier.

It exists because Cloud in a Bottle cannot set environment variables on an
installed app, so these are the settings you can change without a rebuild.
"""

from __future__ import annotations

import pytest

from dashboard.config import Config, config_file_path


@pytest.fixture
def data_dir(clean_env, tmp_path):
    clean_env.setenv("BOTTLE_APP_DATA_DIR", str(tmp_path))
    return tmp_path


def write(path, text: str):
    path.write_text(text.strip() + "\n", encoding="utf-8")


def test_file_is_looked_for_in_the_persistent_tier(data_dir):
    assert config_file_path() == data_dir / "config.toml"


def test_explicit_override_wins(clean_env, tmp_path):
    clean_env.setenv("BOTTLE_APP_DATA_DIR", str(tmp_path))
    clean_env.setenv("DASHBOARD_CONFIG_FILE", "/etc/elsewhere.toml")
    assert str(config_file_path()) == "/etc/elsewhere.toml"


def test_absent_file_is_not_an_error(data_dir):
    config = Config.from_env()
    assert config.warnings == ()
    assert config.title == "Home Dashboard"
    assert config.tz_name == "UTC"


def test_settings_are_read_from_the_file(data_dir):
    write(data_dir / "config.toml", """
        title = "Alan's Home"
        subtitle = "Anchorage"
        timezone = "America/Anchorage"
        refresh_seconds = 900
        calendar_lookahead_days = 3
        http_timeout = 20
    """)
    config = Config.from_env()
    assert config.warnings == ()
    assert config.title == "Alan's Home"
    assert config.subtitle == "Anchorage"
    assert config.tz_name == "America/Anchorage"
    assert config.refresh_seconds == 900
    assert config.calendar_lookahead_days == 3
    assert config.http_timeout == 20.0


def test_environment_overrides_the_file(data_dir, clean_env):
    write(data_dir / "config.toml", """
        title = "From file"
        timezone = "America/Anchorage"
    """)
    clean_env.setenv("DASHBOARD_TITLE", "From env")
    clean_env.setenv("TZ", "Europe/London")
    config = Config.from_env()
    assert config.title == "From env"
    assert config.tz_name == "Europe/London"


def test_the_example_file_in_the_repo_is_valid(clean_env, tmp_path):
    """Guards against the documented example drifting from the parser."""
    import shutil
    from pathlib import Path

    source = Path(__file__).resolve().parents[1] / "config.example.toml"
    shutil.copy(source, tmp_path / "config.toml")
    clean_env.setenv("BOTTLE_APP_DATA_DIR", str(tmp_path))

    config = Config.from_env()
    assert config.warnings == ()
    assert config.tz_name == "America/Anchorage"


# --- a broken file must never stop the page regenerating ---------------------


def test_malformed_toml_warns_and_falls_back(data_dir):
    write(data_dir / "config.toml", "title = 'unterminated")
    config = Config.from_env()
    assert config.title == "Home Dashboard"
    assert any("not valid TOML" in warning for warning in config.warnings)


def test_unknown_key_is_reported(data_dir):
    """A typo'd setting is worse than a missing one: it looks like it works."""
    write(data_dir / "config.toml", """
        title = "Fine"
        timezoen = "America/Anchorage"
    """)
    config = Config.from_env()
    assert config.title == "Fine"
    assert any("'timezoen'" in warning for warning in config.warnings)


def test_wrong_type_is_reported_and_ignored(data_dir):
    write(data_dir / "config.toml", 'refresh_seconds = "soon"')
    config = Config.from_env()
    assert config.refresh_seconds == 1860
    assert any("whole number" in warning for warning in config.warnings)


def test_boolean_is_not_accepted_as_a_number(data_dir):
    """bool subclasses int, so this would otherwise slip through as 1."""
    write(data_dir / "config.toml", "refresh_seconds = true")
    config = Config.from_env()
    assert config.refresh_seconds == 1860
    assert config.warnings


def test_unknown_timezone_warns_on_the_page(data_dir):
    write(data_dir / "config.toml", 'timezone = "Mars/Olympus_Mons"')
    config = Config.from_env()
    assert config.tz_name == "UTC"
    assert any("IANA" in warning for warning in config.warnings)


def test_warnings_are_shown_to_the_reader(data_dir):
    from datetime import datetime

    from dashboard import generate
    from dashboard.sources.base import Panel

    write(data_dir / "config.toml", 'timezoen = "typo"')
    config = Config.from_env()
    html = generate.render(config, [Panel(key="a", title="A")],
                           datetime.now(config.timezone))
    assert "Check your configuration file" in html
    assert "timezoen" in html


def test_process_timezone_follows_the_config_file(data_dir, clean_env):
    """Otherwise `bottle logs` prints UTC beside a page that says Anchorage."""
    import time

    from dashboard.config import apply_process_timezone

    write(data_dir / "config.toml", 'timezone = "America/Anchorage"')
    config = Config.from_env()
    apply_process_timezone(config)

    import os

    assert os.environ["TZ"] == "America/Anchorage"
    assert time.strftime("%Z") in {"AKDT", "AKST"}
