"""Configuration loading, validation, and override management for the EDC agent.

Loads default_config.toml, merges user/per-person overrides, and enforces validation with Pydantic.
"""
from pathlib import Path
from typing import List, Optional, Union
import tomllib
import zoneinfo
from pydantic import BaseModel, ConfigDict, Field, field_validator
import tomli_w


DEFAULT_CONFIG_FILE = Path(__file__).parent / "default_config.toml"


class EDCConfig(BaseModel):
    """Runtime configuration validated per docs/metrics_spec.md Section 2."""
    model_config = ConfigDict(extra="forbid")

    # Time and environment settings
    timezone: str = Field(default="Asia/Kolkata", description="IANA timezone name")
    logical_day_start: str = Field(default="05:00", description="Start time of logical day (HH:MM)")
    logical_day_end: str = Field(default="18:59", description="End time of logical day (HH:MM)")

    # Keyboard thresholds
    typing_gap_max_ms: int = Field(default=2000, description="Max pause within typing flow in ms")
    burst_min_keys: int = Field(default=5, description="Min keys in a typing burst")
    burst_max_flight_ms: int = Field(default=500, description="Max flight time inside a burst in ms")
    long_silence_s: int = Field(default=5, description="Silence after burst counting as long in seconds")
    backspace_burst_min: int = Field(default=3, description="Min backspaces to count as burst")
    backspace_burst_gap_ms: int = Field(default=500, description="Max gap inside a correction run in ms")
    min_flight_intervals: int = Field(default=10, description="Min flight intervals to report mean/std")
    min_keystrokes: int = Field(default=30, description="Min keystrokes to report WPM/ratios")

    # Mouse thresholds
    min_clicks: int = Field(default=5, description="Min clicks to report click interval stats")
    double_click_ms: int = Field(default=500, description="Max delay between clicks for double click in ms")
    double_click_px: int = Field(default=4, description="Max pointer displacement for double click in px")
    rapid_click_n: int = Field(default=3, description="Count of clicks required for rapid click run")
    rapid_click_s: float = Field(default=1.0, description="Window duration for rapid click run in seconds")
    mouse_bin_ms: int = Field(default=100, description="Pointer sampling bin duration in ms")
    mouse_jump_px: int = Field(default=3000, description="Pointer jump threshold to drop (monitor switch)")

    # Activity and Idle thresholds
    idle_threshold_s: int = Field(default=60, description="Input gap that counts as idle in seconds")

    # Session and break thresholds
    session_break_gap_s: int = Field(default=300, description="Gap ending a session / counting as break in seconds")
    break_max_s: int = Field(default=10800, description="Long absence cutoff (3h) in seconds")
    min_session_s: int = Field(default=120, description="Min duration for valid session in seconds")
    extended_session_min: int = Field(default=90, description="Min minutes to count session as extended")
    stretch_break_gap_s: int = Field(default=600, description="Gap ending continuous stretch in seconds")

    # Focus block thresholds
    focus_gap_s: int = Field(default=120, description="Gap interrupting focus block in seconds")
    focus_block_min: int = Field(default=10, description="Min minutes for a focus block")
    deep_work_min: int = Field(default=25, description="Min minutes for a deep work block")

    # Work-hours and schedule thresholds (per-person overridable)
    shift_start: str = Field(default="09:00", description="Shift start time (HH:MM)")
    shift_end: str = Field(default="18:00", description="Shift end time (HH:MM)")
    lunch_window: str = Field(default="12:00-14:00", description="Lunch window range (HH:MM-HH:MM)")
    late_night_window: str = Field(default="22:00-05:00", description="Late-night window range (HH:MM-HH:MM)")
    after_hours_day_min: int = Field(default=30, description="Active after-hours minutes to set daily flag")
    late_night_min: int = Field(default=10, description="Active minutes in late-night window to set flag")
    no_lunch_break_min: int = Field(default=15, description="Threshold below which lunch is deemed skipped")

    # Communication tracking thresholds
    comm_apps: List[str] = Field(
        default_factory=lambda: [
            "slack", "teams", "ms-teams", "outlook", "thunderbird",
            "discord", "whatsapp", "telegram", "signal", "skype", "zoom", "element"
        ],
        description="Process executable name patterns identifying communication apps",
    )
    profile: Optional[str] = Field(
        default=None,
        description="Configured employee role or profile identifier",
    )

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, v: str) -> str:
        try:
            zoneinfo.ZoneInfo(v)
        except Exception as e:
            raise ValueError(f"Invalid IANA timezone '{v}': {e}") from e
        return v

    @field_validator("shift_start", "shift_end", "logical_day_start", "logical_day_end")
    @classmethod
    def validate_time_hh_mm(cls, v: str) -> str:
        parts = v.split(":")
        if len(parts) != 2:
            raise ValueError(f"Time '{v}' must be in HH:MM format")
        try:
            h, m = int(parts[0]), int(parts[1])
            if not (0 <= h < 24 and 0 <= m < 60):
                raise ValueError
        except ValueError as err:
            raise ValueError(f"Time '{v}' contains invalid hour/minute values") from err
        return v

    @field_validator("lunch_window", "late_night_window")
    @classmethod
    def validate_window_range(cls, v: str) -> str:
        parts = v.split("-")
        if len(parts) != 2:
            raise ValueError(f"Window '{v}' must be in HH:MM-HH:MM format")
        cls.validate_time_hh_mm(parts[0].strip())
        cls.validate_time_hh_mm(parts[1].strip())
        return v


def load_config(
    override_path: Optional[Union[str, Path]] = None,
    overrides: Optional[dict] = None,
    default_path: Optional[Union[str, Path]] = None,
) -> EDCConfig:
    """Load default_config.toml, merge an optional user override file, and apply runtime dict overrides."""
    base_file = Path(default_path) if default_path else DEFAULT_CONFIG_FILE
    if not base_file.exists():
        raise FileNotFoundError(f"Default config not found at {base_file}")

    with open(base_file, "rb") as f:
        data = tomllib.load(f)

    if override_path:
        override_file = Path(override_path)
        if override_file.exists():
            with open(override_file, "rb") as f:
                user_data = tomllib.load(f)
                data.update(user_data)
        else:
            raise FileNotFoundError(f"Override config file not found: {override_file}")

    if overrides:
        data.update(overrides)

    return EDCConfig(**data)


def save_config(config: EDCConfig, path: Union[str, Path]) -> None:
    """Write an EDCConfig instance to a TOML file using tomli_w."""
    target_path = Path(path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with open(target_path, "wb") as f:
        tomli_w.dump(config.model_dump(), f)
