"""Unit tests for daily work-hours metrics and RollupDaily aggregation per Spec Section 7.

Validates:
1. Weekend day: all active minutes count as after-hours (after_hours_ratio == 1.0).
2. Late-night day crossing midnight: sets late_night_flag when active mins >= 10.
3. 7-day window with 3 low-coverage days (< 4 valid days with coverage >= 0.5) returns None.
4. Streak of 4 consecutive after-hours days ending today.
5. Simulated 7-day week producing a valid, plausible series of RollupDaily instances.
"""
from datetime import date, datetime, timedelta, timezone as dt_timezone
import zoneinfo
import pytest

from edc_schemas import ActivityEvent, EventKind, RollupDaily
from edc_agent.metrics.workhour_metrics import (
    build_rollup_daily,
    compute_workhour_metrics,
)


def _make_events(timestamps: list[datetime]) -> list[ActivityEvent]:
    """Helper to convert datetimes to ActivityEvents."""
    return [ActivityEvent(ts_utc=ts, kind=EventKind.KEY_CHAR) for ts in timestamps]


def test_weekend_day_all_minutes_after_hours():
    """Verify that on a weekend day, all active minutes are classified as after-hours."""
    # 2026-11-21 is a Saturday
    saturday = date(2026, 11, 21)
    tz = zoneinfo.ZoneInfo("Asia/Kolkata")

    # Generate 45 active minutes between 10:00 and 10:45 IST on Saturday
    t0 = datetime(2026, 11, 21, 10, 0, tzinfo=tz).astimezone(dt_timezone.utc)
    timestamps = [t0 + timedelta(minutes=i) for i in range(45)]
    events = _make_events(timestamps)

    metrics = compute_workhour_metrics(
        events,
        saturday,
        tz_name="Asia/Kolkata",
        shift_start="09:00",
        shift_end="18:00",
    )

    assert metrics["after_hours_active_minutes"] == pytest.approx(45.0)
    assert metrics["after_hours_ratio"] == pytest.approx(1.0)
    assert metrics["late_night_flag"] is False


def test_late_night_day_crossing_midnight():
    """Verify late-night active minutes spanning midnight set late_night_flag."""
    # 2026-11-18 Wednesday night into Thursday morning
    wednesday = date(2026, 11, 18)
    tz = zoneinfo.ZoneInfo("Asia/Kolkata")

    # 15 minutes before midnight (23:45 to 23:59 IST)
    # 15 minutes after midnight (00:00 to 00:14 IST next day)
    t_night = datetime(2026, 11, 18, 23, 45, tzinfo=tz).astimezone(dt_timezone.utc)
    timestamps = [t_night + timedelta(minutes=i) for i in range(30)]
    events = _make_events(timestamps)

    metrics = compute_workhour_metrics(
        events,
        wednesday,
        tz_name="Asia/Kolkata",
        shift_start="09:00",
        shift_end="18:00",
        late_night_window="22:00-05:00",
        late_night_min=10,
    )

    # 30 active minutes are all late night and after hours
    assert metrics["after_hours_active_minutes"] == pytest.approx(30.0)
    assert metrics["late_night_flag"] is True  # 30 >= 10 late_night_min


def test_7d_window_with_low_coverage_days_returns_null():
    """Verify after_hours_ratio_7d_avg returns None if fewer than 4 valid days have coverage >= 0.5."""
    today = date(2026, 11, 20)
    tz = zoneinfo.ZoneInfo("Asia/Kolkata")

    # 7-day history with 3 valid days and 3 low-coverage (< 0.5) days
    history = [
        {"logical_day": today - timedelta(days=6), "coverage_ratio": 0.90, "after_hours_ratio": 0.20},
        {"logical_day": today - timedelta(days=5), "coverage_ratio": 0.85, "after_hours_ratio": 0.30},
        {"logical_day": today - timedelta(days=4), "coverage_ratio": 0.95, "after_hours_ratio": 0.10},
        {"logical_day": today - timedelta(days=3), "coverage_ratio": 0.20, "after_hours_ratio": 0.50},  # Low coverage
        {"logical_day": today - timedelta(days=2), "coverage_ratio": 0.30, "after_hours_ratio": 0.40},  # Low coverage
        {"logical_day": today - timedelta(days=1), "coverage_ratio": 0.40, "after_hours_ratio": 0.60},  # Low coverage
    ]

    # Case A: Today also has low coverage (0.15) -> Total valid days = 3 (< 4 threshold)
    metrics_low = compute_workhour_metrics(
        [],
        today,
        coverage_ratio=0.15,
        history_days=history,
    )
    assert metrics_low["after_hours_ratio_7d_avg"] is None

    # Case B: Today has valid coverage (0.95) and after_hours_ratio 0.40 -> Total valid days = 4
    # Expected mean: (0.20 + 0.30 + 0.10 + 0.40) / 4 = 1.00 / 4 = 0.25
    t0 = datetime(2026, 11, 20, 19, 0, tzinfo=tz).astimezone(dt_timezone.utc)  # After shift
    t1 = datetime(2026, 11, 20, 10, 0, tzinfo=tz).astimezone(dt_timezone.utc)  # In shift
    # 20 mins after shift, 30 mins in shift -> 20 / 50 = 0.40
    events_valid = _make_events([t0 + timedelta(minutes=i) for i in range(20)] + [t1 + timedelta(minutes=i) for i in range(30)])

    metrics_valid = compute_workhour_metrics(
        events_valid,
        today,
        coverage_ratio=0.95,
        history_days=history,
    )
    assert metrics_valid["after_hours_ratio"] == pytest.approx(0.40)
    assert metrics_valid["after_hours_ratio_7d_avg"] == pytest.approx(0.25)


def test_streak_of_4_after_hours_days():
    """Verify consecutive_after_hours_days correctly counts consecutive streak ending today."""
    today = date(2026, 11, 20)
    tz = zoneinfo.ZoneInfo("Asia/Kolkata")

    history = [
        {"logical_day": today - timedelta(days=4), "after_hours_active_minutes": 15.0},  # < 30 (streak broken)
        {"logical_day": today - timedelta(days=3), "after_hours_active_minutes": 45.0},  # >= 30
        {"logical_day": today - timedelta(days=2), "after_hours_active_minutes": 60.0},  # >= 30
        {"logical_day": today - timedelta(days=1), "after_hours_active_minutes": 35.0},  # >= 30
    ]

    # Today has 40 minutes after hours (streak continues -> 4 days)
    t_eve = datetime(2026, 11, 20, 19, 0, tzinfo=tz).astimezone(dt_timezone.utc)
    events_today = _make_events([t_eve + timedelta(minutes=i) for i in range(40)])

    metrics = compute_workhour_metrics(
        events_today,
        today,
        history_days=history,
        after_hours_day_min=30,
    )
    assert metrics["after_hours_active_minutes"] == pytest.approx(40.0)
    assert metrics["consecutive_after_hours_days"] == 4

    # If today had only 10 mins after hours (< 30) -> streak resets to 0
    events_short = _make_events([t_eve + timedelta(minutes=i) for i in range(10)])
    metrics_reset = compute_workhour_metrics(
        events_short,
        today,
        history_days=history,
        after_hours_day_min=30,
    )
    assert metrics_reset["consecutive_after_hours_days"] == 0


def test_simulated_week_produces_believable_rollup_daily_series():
    """Verify a simulated 7-day Monday through Sunday work week builds valid RollupDaily instances."""
    tz = zoneinfo.ZoneInfo("Asia/Kolkata")
    start_monday = date(2026, 11, 16)

    weekly_rollups: list[RollupDaily] = []

    for day_offset in range(7):
        current_date = start_monday + timedelta(days=day_offset)
        weekday_idx = current_date.weekday()

        day_events: list[ActivityEvent] = []

        if weekday_idx < 5:
            # Mon-Fri: Standard working day
            # Morning session: 09:30 to 12:30 IST (180 mins)
            t_morn = datetime(current_date.year, current_date.month, current_date.day, 9, 30, tzinfo=tz).astimezone(dt_timezone.utc)
            day_events.extend(_make_events([t_morn + timedelta(minutes=m) for m in range(181)]))

            # Lunch break: 12:30 to 13:15 IST (45 mins idle gap)

            # Afternoon session: 13:15 to 17:45 IST (270 mins)
            t_afternoon = datetime(current_date.year, current_date.month, current_date.day, 13, 15, tzinfo=tz).astimezone(dt_timezone.utc)
            day_events.extend(_make_events([t_afternoon + timedelta(minutes=m) for m in range(271)]))

            # Occasional overtime on Wednesday and Thursday (18:30 to 19:15, 45 mins)
            if weekday_idx in (2, 3):
                t_eve = datetime(current_date.year, current_date.month, current_date.day, 18, 30, tzinfo=tz).astimezone(dt_timezone.utc)
                day_events.extend(_make_events([t_eve + timedelta(minutes=m) for m in range(46)]))

        elif weekday_idx == 5:
            # Saturday: Catch-up study session (10:00 to 11:00, 60 mins)
            t_sat = datetime(current_date.year, current_date.month, current_date.day, 10, 0, tzinfo=tz).astimezone(dt_timezone.utc)
            day_events.extend(_make_events([t_sat + timedelta(minutes=m) for m in range(60)]))

        else:
            # Sunday: Completely off (0 events)
            day_events = []

        rollup = build_rollup_daily(
            logical_day=current_date,
            events=day_events,
            coverage_ratio=0.98,
            history_days=weekly_rollups,
            tz_name="Asia/Kolkata",
            shift_start="09:00",
            shift_end="18:00",
        )

        assert isinstance(rollup, RollupDaily)
        assert rollup.logical_day == current_date
        assert rollup.day == current_date.isoformat()
        assert rollup.day_of_week == weekday_idx
        assert rollup.is_weekend == (weekday_idx in (5, 6))

        # Check domain plausibility
        if weekday_idx < 5:
            assert rollup.total_breaks_count >= 1
            assert rollup.longest_lunch_break_mins == pytest.approx(45.0)
            assert rollup.lunch_skipped_flag is False
        elif weekday_idx == 5:
            assert rollup.after_hours_ratio == pytest.approx(1.0)
            assert rollup.is_weekend is True
        else:
            assert rollup.total_breaks_count == 0
            assert rollup.avg_session_duration_mins is None

        weekly_rollups.append(rollup)

    # 7 complete RollupDaily objects
    assert len(weekly_rollups) == 7
    # 7-day average on Sunday should be computed across valid days
    sunday_rollup = weekly_rollups[6]
    assert sunday_rollup.after_hours_ratio_7d_avg is not None
