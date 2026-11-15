"""Tests for EDC configuration loading, validation, and overrides."""
from pathlib import Path
import pytest
from pydantic import ValidationError

from edc_agent.config import EDCConfig, load_config, save_config


def test_load_default_config():
    """Verify loading default_config.toml produces valid config matching spec."""
    cfg = load_config()
    assert cfg.timezone == "Asia/Kolkata"
    assert cfg.logical_day_start == "07:00"
    assert cfg.logical_day_end == "19:00"
    assert cfg.typing_gap_max_ms == 2000
    assert cfg.session_break_gap_s == 300
    assert cfg.break_max_s == 10800
    assert cfg.shift_start == "09:00"
    assert cfg.shift_end == "18:00"
    assert cfg.lunch_window == "12:00-14:00"


def test_user_override_file(tmp_path: Path):
    """Verify overriding configuration from an external TOML file."""
    override_file = tmp_path / "user_overrides.toml"
    override_file.write_text(
        """
        shift_start = "08:30"
        shift_end = "17:30"
        lunch_window = "13:00-14:00"
        timezone = "Europe/London"
        min_keystrokes = 45
        """,
        encoding="utf-8",
    )

    cfg = load_config(override_path=override_file)
    assert cfg.shift_start == "08:30"
    assert cfg.shift_end == "17:30"
    assert cfg.lunch_window == "13:00-14:00"
    assert cfg.timezone == "Europe/London"
    assert cfg.min_keystrokes == 45
    # Non-overridden values remain default
    assert cfg.typing_gap_max_ms == 2000
    assert cfg.logical_day_start == "07:00"


def test_per_person_runtime_overrides():
    """Verify runtime per-person dictionary overrides for shift, lunch, timezone."""
    overrides = {
        "shift_start": "10:00",
        "shift_end": "19:00",
        "lunch_window": "13:30-15:00",
        "timezone": "America/New_York",
    }
    cfg = load_config(overrides=overrides)
    assert cfg.shift_start == "10:00"
    assert cfg.shift_end == "19:00"
    assert cfg.lunch_window == "13:30-15:00"
    assert cfg.timezone == "America/New_York"


def test_invalid_timezone_rejected():
    """Verify invalid IANA timezone string raises ValidationError."""
    with pytest.raises(ValidationError):
        load_config(overrides={"timezone": "Invalid/Timezone_Name"})


def test_invalid_time_format_rejected():
    """Verify malformed HH:MM time raises ValidationError."""
    with pytest.raises(ValidationError):
        load_config(overrides={"shift_start": "25:00"})

    with pytest.raises(ValidationError):
        load_config(overrides={"shift_end": "9:00 AM"})


def test_invalid_window_format_rejected():
    """Verify malformed HH:MM-HH:MM window range raises ValidationError."""
    with pytest.raises(ValidationError):
        load_config(overrides={"lunch_window": "12:00 to 14:00"})


def test_extra_fields_forbidden():
    """Verify unknown fields are rejected."""
    with pytest.raises(ValidationError):
        load_config(overrides={"custom_illegal_field": 123})
