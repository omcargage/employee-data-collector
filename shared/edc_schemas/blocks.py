"""Window building blocks representing additive sufficient statistics for a 15-minute window.

Enables exact recomputation and linear merging across time intervals without loss of precision.
"""
from pydantic import BaseModel, ConfigDict, Field


class WindowBlocks(BaseModel):
    """Raw counts and sufficient statistics for a 15-minute window per Spec Section 3.

    All counts, sums, and sum-of-squares are additive across windows.
    """
    model_config = ConfigDict(extra="forbid")

    # Keystroke and correction event counts
    n_char: int = Field(default=0, description="Count of printable character keystrokes")
    n_backspace: int = Field(default=0, description="Count of backspace keystrokes")
    n_delete: int = Field(default=0, description="Count of delete keystrokes")
    n_other_key: int = Field(default=0, description="Count of other keys (enter, tab, arrows, etc.)")

    # Mouse event counts
    n_clicks: int = Field(default=0, description="Count of button-down clicks")
    n_double_clicks: int = Field(default=0, description="Count of double click occurrences")
    n_rapid_click_runs: int = Field(default=0, description="Count of rapid repeated click sequences")
    n_scroll_ticks_abs: int = Field(default=0, description="Sum of absolute scroll ticks")
    n_scroll_reversals: int = Field(default=0, description="Count of rapid scroll direction reversals")

    # Flight times (ms, gaps <= typing_gap_max_ms)
    flight_time_n: int = Field(default=0, description="Number of observed inter-key flight intervals")
    flight_time_sum_ms: float = Field(default=0.0, description="Sum of flight times in milliseconds")
    flight_time_sum_sq_ms: float = Field(default=0.0, description="Sum of squared flight times in ms^2")

    # Fixed flight-time histogram bins
    flight_bin_0_100: int = Field(default=0, description="Flight intervals between 0 and 100 ms")
    flight_bin_100_200: int = Field(default=0, description="Flight intervals between 100 and 200 ms")
    flight_bin_200_300: int = Field(default=0, description="Flight intervals between 200 and 300 ms")
    flight_bin_300_500: int = Field(default=0, description="Flight intervals between 300 and 500 ms")
    flight_bin_500_1000: int = Field(default=0, description="Flight intervals between 500 and 1000 ms")
    flight_bin_1000_2000: int = Field(default=0, description="Flight intervals between 1000 and 2000 ms")

    # Click intervals (s, gaps <= 5.0 s)
    click_interval_n: int = Field(default=0, description="Number of click intervals <= 5s")
    click_interval_sum_s: float = Field(default=0.0, description="Sum of click intervals in seconds")
    click_interval_sum_sq_s: float = Field(default=0.0, description="Sum of squared click intervals in s^2")

    # Pointer movement statistics
    n_moving_bins: int = Field(default=0, description="Number of mouse sample bins with movement")
    sum_speed_px_s: float = Field(default=0.0, description="Sum of speed samples in px/s")
    n_accel_samples: int = Field(default=0, description="Number of acceleration samples across bins")
    sum_abs_accel_px_s2: float = Field(default=0.0, description="Sum of absolute acceleration in px/s^2")
    display_scale: float = Field(default=1.0, description="Display scale factor recorded alongside pointer speed")

    # Time counters
    covered_s: float = Field(default=0.0, description="Seconds agent was active and listening")
    active_typing_s: float = Field(default=0.0, description="Sum of flight times <= typing_gap_max_ms")
    active_minutes: int = Field(default=0, description="Calendar minutes with at least one active input")
    idle_s: float = Field(default=0.0, description="Total seconds of detected idle time")

    # Burst statistics
    n_bursts: int = Field(default=0, description="Number of detected typing bursts")
    sum_burst_len: int = Field(default=0, description="Total characters typed within bursts")
    n_long_silences_after_burst: int = Field(default=0, description="Count of bursts followed by long silence")

    # Correction statistics
    n_correction_runs: int = Field(default=0, description="Number of correction runs")
    n_backspace_bursts: int = Field(default=0, description="Number of rapid repeated backspace bursts")
    sum_pause_before_correction_ms: float = Field(default=0.0, description="Sum of pauses before corrections in ms")

    # Key dwell time (optional, reported only if key_dwell capability is supported)
    dwell_n: int = Field(default=0, description="Count of key hold dwell observations")
    dwell_sum_ms: float = Field(default=0.0, description="Sum of key hold dwell times in ms")
    dwell_sum_sq_ms: float = Field(default=0.0, description="Sum of squared key dwell times in ms^2")

    def merge(self, other: "WindowBlocks") -> "WindowBlocks":
        """Merge two WindowBlocks by summing all additive counts, sums, and histogram bins."""
        merged_data = {}
        for field_name in self.__class__.model_fields:
            if field_name == "display_scale":
                merged_data[field_name] = other.display_scale if other.display_scale != 1.0 else self.display_scale
            else:
                val_self = getattr(self, field_name)
                val_other = getattr(other, field_name)
                merged_data[field_name] = val_self + val_other
        return WindowBlocks(**merged_data)

    def __add__(self, other: "WindowBlocks") -> "WindowBlocks":
        return self.merge(other)
