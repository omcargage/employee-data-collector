"""Tests for time logic, logical day boundaries, timezone conversions, and coverage tracking."""
from datetime import date, datetime, timedelta, timezone
import zoneinfo
import pytest

from edc_agent.timeutil import (
    CoverageTracker,
    is_weekend,
    local_decimal_hour,
    to_logical_day,
    window_bounds,
)


def test_session_crossing_midnight_stays_in_one_logical_day():
    """Verify that late-night activity crossing calendar midnight belongs to the same logical day.

    Logical day begins at 05:00 local time. Activity at 23:30, 00:30, 01:30, and 04:45
    all belong to the previous day's logical day.
    """
    tz = "Asia/Kolkata"
    # In IST (UTC + 5:30):
    # 2026-11-15 23:30 IST -> UTC 2026-11-15 18:00
    ts_2330 = datetime(2026, 11, 15, 18, 0, tzinfo=timezone.utc)
    # 2026-11-16 00:30 IST -> UTC 2026-11-15 19:00
    ts_0030 = datetime(2026, 11, 15, 19, 0, tzinfo=timezone.utc)
    # 2026-11-16 01:30 IST -> UTC 2026-11-15 20:00
    ts_0130 = datetime(2026, 11, 15, 20, 0, tzinfo=timezone.utc)
    # 2026-11-16 04:45 IST -> UTC 2026-11-15 23:15
    ts_0445 = datetime(2026, 11, 15, 23, 15, tzinfo=timezone.utc)
    # 2026-11-16 05:00 IST -> UTC 2026-11-15 23:30 (New logical day begins)
    ts_0500 = datetime(2026, 11, 15, 23, 30, tzinfo=timezone.utc)

    expected_day = date(2026, 11, 15)
    assert to_logical_day(ts_2330, tz, day_start_hour=5) == expected_day
    assert to_logical_day(ts_0030, tz, day_start_hour=5) == expected_day
    assert to_logical_day(ts_0130, tz, day_start_hour=5) == expected_day
    assert to_logical_day(ts_0445, tz, day_start_hour=5) == expected_day

    # 05:00 marks the start of the next logical day
    assert to_logical_day(ts_0500, tz, day_start_hour=5) == date(2026, 11, 16)


def test_dst_change_in_europe_berlin():
    """Verify time conversions and window bounds during DST transitions in Europe/Berlin."""
    tz = "Europe/Berlin"

    # Spring forward: Sunday 2026-03-29 (clocks jump from 02:00 to 03:00)
    # 01:45 CET (UTC 00:45) is before jump
    ts_pre_jump = datetime(2026, 3, 29, 0, 45, tzinfo=timezone.utc)
    w_start, w_end = window_bounds(ts_pre_jump, tz)
    assert (w_end - w_start) == timedelta(minutes=15)
    assert to_logical_day(ts_pre_jump, tz, day_start_hour=5) == date(2026, 3, 28)

    # 03:15 CEST (UTC 01:15) is right after jump
    ts_post_jump = datetime(2026, 3, 29, 1, 15, tzinfo=timezone.utc)
    w_start, w_end = window_bounds(ts_post_jump, tz)
    assert (w_end - w_start) == timedelta(minutes=15)
    assert to_logical_day(ts_post_jump, tz, day_start_hour=5) == date(2026, 3, 28)

    # Fall back: Sunday 2026-10-25 (clocks repeat 02:00 to 03:00)
    # Event during the repeated hour
    ts_fall_back = datetime(2026, 10, 25, 1, 30, tzinfo=timezone.utc)
    w_start, w_end = window_bounds(ts_fall_back, tz)
    assert (w_end - w_start) == timedelta(minutes=15)
    assert to_logical_day(ts_fall_back, tz, day_start_hour=5) == date(2026, 10, 24)


def test_window_straddles_day_boundary():
    """Verify window bounds and day mapping right around calendar midnight and logical day start."""
    tz = "Asia/Kolkata"

    # 1. Right before calendar midnight: 23:55 IST (UTC 18:25)
    ts_pre_midnight = datetime(2026, 11, 15, 18, 25, tzinfo=timezone.utc)
    start_utc, end_utc = window_bounds(ts_pre_midnight, tz)
    # Window should be 23:45 to 00:00 IST -> UTC 18:15 to 18:30
    assert start_utc == datetime(2026, 11, 15, 18, 15, tzinfo=timezone.utc)
    assert end_utc == datetime(2026, 11, 15, 18, 30, tzinfo=timezone.utc)

    # 2. Right after calendar midnight: 00:05 IST (UTC 18:35)
    ts_post_midnight = datetime(2026, 11, 15, 18, 35, tzinfo=timezone.utc)
    start_utc, end_utc = window_bounds(ts_post_midnight, tz)
    # Window should be 00:00 to 00:15 IST -> UTC 18:30 to 18:45
    assert start_utc == datetime(2026, 11, 15, 18, 30, tzinfo=timezone.utc)
    assert end_utc == datetime(2026, 11, 15, 18, 45, tzinfo=timezone.utc)

    # 3. Straddling logical day boundary: 04:55 IST (UTC 23:25 on Nov 15)
    ts_pre_cutoff = datetime(2026, 11, 15, 23, 25, tzinfo=timezone.utc)
    start_utc, end_utc = window_bounds(ts_pre_cutoff, tz)
    # Window is 04:45 to 05:00 IST -> UTC 23:15 to 23:30
    assert start_utc == datetime(2026, 11, 15, 23, 15, tzinfo=timezone.utc)
    assert end_utc == datetime(2026, 11, 15, 23, 30, tzinfo=timezone.utc)
    assert to_logical_day(ts_pre_cutoff, tz, day_start_hour=5) == date(2026, 11, 15)


def test_asia_kolkata_no_dst():
    """Verify Asia/Kolkata maintains strict UTC+5:30 offset across summer and winter months."""
    tz = "Asia/Kolkata"

    # Winter date (January)
    ts_jan = datetime(2026, 1, 15, 6, 30, tzinfo=timezone.utc)  # 12:00 IST
    start_utc, end_utc = window_bounds(ts_jan, tz)
    assert (end_utc - start_utc) == timedelta(minutes=15)
    assert local_decimal_hour(ts_jan, tz) == 12.0

    # Summer date (July)
    ts_jul = datetime(2026, 7, 15, 6, 30, tzinfo=timezone.utc)  # 12:00 IST
    start_utc, end_utc = window_bounds(ts_jul, tz)
    assert (end_utc - start_utc) == timedelta(minutes=15)
    assert local_decimal_hour(ts_jul, tz) == 12.0


def test_coverage_tracker_started_mid_window():
    """Verify coverage calculation when agent starts mid-window or has pauses."""
    tracker = CoverageTracker()
    base = datetime(2026, 11, 15, 10, 0, tzinfo=timezone.utc)
    window_start = base
    window_end = base + timedelta(minutes=15)  # 900 seconds

    # Case A: Agent starts 6 minutes into window (runs 10:06 to 10:15 = 9 mins = 540s)
    tracker.record_interval(base + timedelta(minutes=6), window_end)
    # Expected ratio = 540 / 900 = 0.60
    assert tracker.coverage_seconds(window_start, window_end) == pytest.approx(540.0)
    assert tracker.coverage_ratio(window_start, window_end) == pytest.approx(0.60)


def test_coverage_tracker_with_pause_and_merges():
    """Verify coverage tracker correctly merges overlapping intervals and respects pauses."""
    tracker = CoverageTracker()
    base = datetime(2026, 11, 15, 10, 0, tzinfo=timezone.utc)
    window_start = base
    window_end = base + timedelta(minutes=15)  # 900 seconds

    # Interval 1: 10:00 to 10:05 (300s)
    tracker.record_interval(base, base + timedelta(minutes=5))
    # Interval 2 (overlapping with 1): 10:04 to 10:07 (extends interval 1 to 10:07 = 420s)
    tracker.record_interval(base + timedelta(minutes=4), base + timedelta(minutes=7))
    # 2-minute pause between 10:07 and 10:09
    # Interval 3: 10:09 to 10:15 (360s)
    tracker.record_interval(base + timedelta(minutes=9), window_end)

    # Total covered seconds: 420 + 360 = 780s
    # Total ratio: 780 / 900 = 0.8667
    assert tracker.coverage_seconds(window_start, window_end) == pytest.approx(780.0)
    assert tracker.coverage_ratio(window_start, window_end) == pytest.approx(780.0 / 900.0)


def test_is_weekend_and_decimal_hour():
    """Verify weekend detection and decimal hour accuracy."""
    # 2026-11-15 is Sunday (day_of_week = 6) -> Weekend
    assert is_weekend(date(2026, 11, 15)) is True
    # 2026-11-16 is Monday (day_of_week = 0) -> Weekday
    assert is_weekend(date(2026, 11, 16)) is False

    # Decimal hour for 14:45:00 -> 14 + 45/60 = 14.75
    dt = datetime(2026, 11, 15, 14, 45, 0, tzinfo=timezone.utc)
    assert local_decimal_hour(dt) == 14.75
