"""Rollup schemas for 15-minute windows and daily intervals.

Enforces strict field boundaries; all metric values are optional to support null rules for missing data.
"""
from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field

from .blocks import WindowBlocks


class Rollup15Min(BaseModel):
    """Aggregated 15-minute rollup combining keyboard/mouse metrics and sufficient block statistics."""
    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default="1.0.0", description="Contract schema version")
    agent_version: str = Field(default="0.1.0", description="Agent version that produced the rollup")

    # Window timestamps (UTC)
    window_start: datetime = Field(description="Window start timestamp (UTC)")
    window_end: datetime = Field(description="Window end timestamp (UTC)")

    # Coverage metrics
    coverage_ratio: float = Field(description="Ratio of covered listening time to window duration")
    low_coverage: bool = Field(description="True if coverage_ratio < 0.5")

    # Time context
    day_of_week: Optional[int] = Field(default=None, description="0=Monday ... 6=Sunday")
    is_weekend: Optional[bool] = Field(default=None, description="True for weekend logical days")
    hour_of_day: Optional[int] = Field(default=None, description="Local hour of window start (0-23)")
    decimal_hour: Optional[float] = Field(default=None, description="Local decimal hour of window start")
    session_index_in_day: Optional[int] = Field(default=None, description="1-based index of active session")

    # Keyboard metrics (Optional, null if insufficient data per spec)
    total_keystrokes: Optional[int] = Field(default=None, description="Total key event count")
    char_keystrokes: Optional[int] = Field(default=None, description="Character keystroke count")
    backspace_count: Optional[int] = Field(default=None, description="Backspace count")
    delete_count: Optional[int] = Field(default=None, description="Delete count")
    total_correction_keys: Optional[int] = Field(default=None, description="Backspace + delete count")
    repeated_backspace_bursts: Optional[int] = Field(default=None, description="Count of backspace bursts")
    mean_flight_time_ms: Optional[float] = Field(default=None, description="Mean flight time in ms")
    flight_time_std_ms: Optional[float] = Field(default=None, description="Std dev of flight times in ms")
    active_typing_ratio: Optional[float] = Field(default=None, description="Ratio of active typing time to covered time")
    gross_wpm: Optional[float] = Field(default=None, description="Gross words per minute")
    net_wpm: Optional[float] = Field(default=None, description="Net words per minute")
    backspace_ratio: Optional[float] = Field(default=None, description="Backspace ratio")
    correction_ratio: Optional[float] = Field(default=None, description="Total corrections ratio")
    error_correction_efficiency: Optional[float] = Field(default=None, description="Fraction of chars surviving corrections")
    pause_before_correction_ms: Optional[float] = Field(default=None, description="Mean pause before correction in ms")
    n_bursts: Optional[int] = Field(default=None, description="Typing bursts count")
    mean_burst_len: Optional[float] = Field(default=None, description="Mean keys per typing burst")
    n_long_silences_after_burst: Optional[int] = Field(default=None, description="Count of long silences following bursts")
    burst_to_silence_ratio: Optional[float] = Field(default=None, description="Ratio of bursts to long silences")
    keystrokes_per_second: Optional[float] = Field(default=None, description="Keystrokes per covered second")
    keystroke_coefficient_of_variation: Optional[float] = Field(default=None, description="CV of flight times")
    mean_dwell_time_ms: Optional[float] = Field(default=None, description="Mean key hold dwell time in ms")
    dwell_time_std_ms: Optional[float] = Field(default=None, description="Std dev of key dwell times in ms")

    # Mouse metrics (Optional, null if insufficient data per spec)
    click_count: Optional[int] = Field(default=None, description="Total click count")
    clicks_per_second: Optional[float] = Field(default=None, description="Clicks per covered second")
    average_interval_seconds: Optional[float] = Field(default=None, description="Mean inter-click interval in seconds")
    click_interval_stdev_seconds: Optional[float] = Field(default=None, description="Std dev of click intervals")
    coefficient_of_variation: Optional[float] = Field(default=None, description="CV of click intervals")
    average_speed_px_s: Optional[float] = Field(default=None, description="Mean pointer speed in px/s")
    average_abs_accel_px_s2: Optional[float] = Field(default=None, description="Mean pointer acceleration in px/s^2")
    total_abs_scroll_ticks: Optional[int] = Field(default=None, description="Total absolute scroll ticks")
    average_abs_scroll_ticks_s: Optional[float] = Field(default=None, description="Scroll ticks per covered second")
    double_click_count: Optional[int] = Field(default=None, description="Double clicks count")
    rapid_click_runs: Optional[int] = Field(default=None, description="Rapid repeated clicking sequences")
    scroll_reversal_count: Optional[int] = Field(default=None, description="Scroll direction reversals count")
    pointer_idle_s: Optional[float] = Field(default=None, description="Seconds without mouse input")
    short_idle_total_s: Optional[float] = Field(default=None, description="Combined keyboard/mouse silence (60s-300s)")

    # Underlying additive sufficient statistics
    blocks: WindowBlocks = Field(description="Underlying additive sufficient statistics for exact window merging")


class RollupDaily(BaseModel):
    """Daily aggregated rollup for session, stretch, lunch, focus, and work-hours metrics."""
    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default="1.0.0", description="Contract schema version")
    agent_version: str = Field(default="0.1.0", description="Agent version that produced the rollup")

    # Day metadata
    logical_day: date = Field(description="Logical day date (YYYY-MM-DD)")
    coverage_ratio: float = Field(description="Daily coverage ratio")
    low_coverage: bool = Field(default=False, description="True if daily coverage_ratio < 0.5")

    day: Optional[str] = Field(default=None, description="Date formatted as string YYYY-MM-DD")
    day_of_week: Optional[int] = Field(default=None, description="0=Monday ... 6=Sunday")
    is_weekend: Optional[bool] = Field(default=None, description="True for weekend logical days")

    # Session & break metrics
    avg_session_duration_mins: Optional[float] = Field(default=None, description="Mean session duration in minutes")
    max_session_duration_mins: Optional[float] = Field(default=None, description="Longest session in minutes")
    total_breaks_count: Optional[int] = Field(default=None, description="Total break count")
    avg_break_duration_mins: Optional[float] = Field(default=None, description="Mean break duration in minutes")
    extended_sessions_count: Optional[int] = Field(default=None, description="Count of sessions >= extended_session_min")

    # Continuous stretch metrics
    longest_stretch_duration_mins: Optional[float] = Field(default=None, description="Longest continuous stretch in minutes")
    stretch_start_hour: Optional[float] = Field(default=None, description="Local decimal hour when stretch started")
    post_stretch_break_mins: Optional[float] = Field(default=None, description="Break length immediately following stretch")
    stretch_intensity_pct: Optional[float] = Field(default=None, description="Percentage of stretch minutes with active input")
    stretch_to_total_work_ratio: Optional[float] = Field(default=None, description="Longest stretch divided by total work time")

    # Lunch metrics
    lunch_active_mins: Optional[float] = Field(default=None, description="Active input minutes during lunch window")
    longest_lunch_break_mins: Optional[float] = Field(default=None, description="Longest break overlapping lunch window")
    lunch_work_ratio: Optional[float] = Field(default=None, description="Fraction of lunch window spent active")
    lunch_skipped_flag: Optional[bool] = Field(default=None, description="True if longest lunch break < no_lunch_break_min")

    # Focus block metrics
    avg_focus_block_mins: Optional[float] = Field(default=None, description="Mean focus block duration in minutes")
    max_focus_block_mins: Optional[float] = Field(default=None, description="Longest focus block duration in minutes")
    deep_work_blocks_count: Optional[int] = Field(default=None, description="Count of blocks >= deep_work_min")
    total_focus_time_hours: Optional[float] = Field(default=None, description="Total focus block hours")
    focus_fragmentation_ratio: Optional[float] = Field(default=None, description="Fragmentation ratio (1 - focus/work)")

    # Work-hours and after-hours metrics
    shift_start: Optional[str] = Field(default=None, description="Configured shift start time HH:MM")
    shift_end: Optional[str] = Field(default=None, description="Configured shift end time HH:MM")
    after_hours_active_minutes: Optional[float] = Field(default=None, description="Active minutes outside shift hours")
    after_hours_ratio: Optional[float] = Field(default=None, description="Ratio of after-hours active time to total active time")
    late_night_flag: Optional[bool] = Field(default=None, description="True if active minutes in late_night_window >= threshold")
    after_hours_ratio_7d_avg: Optional[float] = Field(default=None, description="7-day rolling average of after-hours ratio")
    consecutive_after_hours_days: Optional[int] = Field(default=None, description="Consecutive days with after-hours activity")
