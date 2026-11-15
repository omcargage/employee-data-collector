"""Unit tests for daily session, break, stretch, lunch, and focus metrics per Spec Section 6.

Validates:
1. Day with a standard lunch break.
2. Day with no breaks.
3. Session crossing midnight (duration computed correctly without negative wrap).
4. Unknown gap (agent crash / missing data): NEVER counts as a break.
5. Laptop-locked lunch (GapType.AWAY): counts as a valid break.
6. Break longer than break_max_s (3 hours): long absence, excluded from avg_break_duration_mins.
7. Candidate sessions below min_session_s (120 s): ignored in session stats.
8. desk_dining_flag stays None per specification decision.
9. Continuous stretch and focus/deep-work blocks.
"""
from datetime import datetime, timedelta, timezone as dt_timezone
import zoneinfo
import pytest

from edc_schemas import ActivityEvent, EventKind
from edc_agent.collectors.gap_classifier import GapType
from edc_agent.metrics.session_metrics import (
    ClassifiedGap,
    compute_session_metrics,
)


def _generate_active_events(start_dt: datetime, duration_mins: float, step_s: float = 30.0) -> list[ActivityEvent]:
    """Helper generating events with gaps < session_break_gap_s to form a single session."""
    events = []
    total_seconds = int(duration_mins * 60)
    for s in range(0, total_seconds + 1, int(step_s)):
        events.append(
            ActivityEvent(
                ts_utc=start_dt + timedelta(seconds=s),
                kind=EventKind.KEY_CHAR,
            )
        )
    return events


def test_day_with_lunch_break():
    """Verify standard day with a 45-minute lunch break."""
    # Local day: 2026-11-15 Asia/Kolkata (+05:30)
    # 09:00 IST = 03:30 UTC
    tz = zoneinfo.ZoneInfo("Asia/Kolkata")
    t_start = datetime(2026, 11, 15, 9, 0, tzinfo=tz).astimezone(dt_timezone.utc)

    # Session 1: 09:00 to 12:30 IST (210 mins = 3.5 h)
    s1_events = _generate_active_events(t_start, duration_mins=210.0, step_s=60.0)

    # Lunch break: 12:30 to 13:15 IST (45 mins idle break)
    t_s2 = datetime(2026, 11, 15, 13, 15, tzinfo=tz).astimezone(dt_timezone.utc)

    # Session 2: 13:15 to 17:30 IST (255 mins = 4.25 h)
    s2_events = _generate_active_events(t_s2, duration_mins=255.0, step_s=60.0)

    all_events = s1_events + s2_events
    metrics = compute_session_metrics(all_events, tz_name="Asia/Kolkata")

    # 1. Sessions: 2 valid sessions (210 mins, 255 mins)
    assert metrics["avg_session_duration_mins"] == pytest.approx((210.0 + 255.0) / 2.0)  # 232.5 mins
    assert metrics["max_session_duration_mins"] == pytest.approx(255.0)
    assert metrics["extended_sessions_count"] == 2  # Both >= 90 mins

    # 2. Breaks: 1 break of 45 mins
    assert metrics["total_breaks_count"] == 1
    assert metrics["avg_break_duration_mins"] == pytest.approx(45.0)

    # 3. Lunch metrics
    # Lunch window is 12:00 to 14:00 (120 mins)
    # Active from 12:00-12:30 (31 active calendar mins) and 13:15-14:00 (46 active calendar mins) -> 77 active mins
    assert metrics["lunch_active_mins"] == pytest.approx(77.0)
    assert metrics["longest_lunch_break_mins"] == pytest.approx(45.0)
    assert metrics["lunch_skipped_flag"] is False  # 45 >= 15 min no_lunch_break_min
    assert metrics["desk_dining_flag"] is None


def test_day_with_no_breaks():
    """Verify day with one continuous session and zero breaks."""
    tz = zoneinfo.ZoneInfo("Asia/Kolkata")
    t_start = datetime(2026, 11, 15, 9, 0, tzinfo=tz).astimezone(dt_timezone.utc)

    # Continuous session from 09:00 to 11:00 (120 mins) with step 30s
    events = _generate_active_events(t_start, duration_mins=120.0, step_s=30.0)

    metrics = compute_session_metrics(events, tz_name="Asia/Kolkata")

    assert metrics["total_breaks_count"] == 0
    assert metrics["avg_break_duration_mins"] is None
    assert metrics["avg_session_duration_mins"] == pytest.approx(120.0)
    assert metrics["max_session_duration_mins"] == pytest.approx(120.0)


def test_session_crossing_midnight():
    """Verify session running across midnight computes exact duration."""
    tz = zoneinfo.ZoneInfo("Asia/Kolkata")
    # Start at 23:30 local time and run for 60 mins until 00:30 next day
    t_start = datetime(2026, 11, 15, 23, 30, tzinfo=tz).astimezone(dt_timezone.utc)
    events = _generate_active_events(t_start, duration_mins=60.0, step_s=30.0)

    metrics = compute_session_metrics(events, tz_name="Asia/Kolkata")

    assert metrics["avg_session_duration_mins"] == pytest.approx(60.0)
    assert metrics["max_session_duration_mins"] == pytest.approx(60.0)
    assert metrics["total_breaks_count"] == 0


def test_unknown_gap_never_a_break():
    """Verify an unknown gap (agent crash / missing heartbeat) is NEVER classified as a break."""
    tz = zoneinfo.ZoneInfo("Asia/Kolkata")
    t1 = datetime(2026, 11, 15, 9, 0, tzinfo=tz).astimezone(dt_timezone.utc)

    # Session 1: 09:00 to 10:00 (60 mins)
    s1_events = _generate_active_events(t1, duration_mins=60.0, step_s=30.0)

    # Gap of 60 mins from 10:00 to 11:00, classified as UNKNOWN (agent crash)
    t_gap_start = s1_events[-1].ts_utc
    t2 = datetime(2026, 11, 15, 11, 0, tzinfo=tz).astimezone(dt_timezone.utc)
    t_gap_end = t2

    # Session 2: 11:00 to 12:00 (60 mins)
    s2_events = _generate_active_events(t2, duration_mins=60.0, step_s=30.0)

    classified_gaps = [
        ClassifiedGap(start_utc=t_gap_start, end_utc=t_gap_end, gap_type=GapType.UNKNOWN),
    ]

    metrics = compute_session_metrics(
        s1_events + s2_events,
        classified_gaps=classified_gaps,
        tz_name="Asia/Kolkata",
    )

    # Sessions are valid (60 mins each)
    assert metrics["avg_session_duration_mins"] == pytest.approx(60.0)
    # But the gap is UNKNOWN -> MUST NEVER be counted as a break!
    assert metrics["total_breaks_count"] == 0
    assert metrics["avg_break_duration_mins"] is None


def test_laptop_locked_lunch_away_counts_as_break():
    """Verify lunch with laptop locked (GapType.AWAY) is counted as a valid break."""
    tz = zoneinfo.ZoneInfo("Asia/Kolkata")
    t1 = datetime(2026, 11, 15, 9, 0, tzinfo=tz).astimezone(dt_timezone.utc)

    # Session 1: 09:00 to 12:00 (180 mins)
    s1_events = _generate_active_events(t1, duration_mins=180.0, step_s=60.0)

    # Laptop locked from 12:00 to 12:45 (45 mins AWAY gap)
    t_lock = s1_events[-1].ts_utc
    t2 = datetime(2026, 11, 15, 12, 45, tzinfo=tz).astimezone(dt_timezone.utc)
    t_unlock = t2

    # Session 2: 12:45 to 17:00 (255 mins)
    s2_events = _generate_active_events(t2, duration_mins=255.0, step_s=60.0)

    classified_gaps = [
        ClassifiedGap(start_utc=t_lock, end_utc=t_unlock, gap_type=GapType.AWAY),
    ]

    metrics = compute_session_metrics(
        s1_events + s2_events,
        classified_gaps=classified_gaps,
        tz_name="Asia/Kolkata",
    )

    # AWAY gap counts as a valid break
    assert metrics["total_breaks_count"] == 1
    assert metrics["avg_break_duration_mins"] == pytest.approx(45.0)
    assert metrics["longest_lunch_break_mins"] == pytest.approx(45.0)
    assert metrics["lunch_skipped_flag"] is False


def test_break_longer_than_break_max_s():
    """Verify gaps > break_max_s (3 hours) are long absences, excluded from avg_break_duration_mins."""
    tz = zoneinfo.ZoneInfo("Asia/Kolkata")
    t1 = datetime(2026, 11, 15, 9, 0, tzinfo=tz).astimezone(dt_timezone.utc)

    # Session 1: 09:00 to 11:00 (120 mins)
    s1_events = _generate_active_events(t1, duration_mins=120.0, step_s=60.0)

    # Long absence of 4 hours (240 mins > 180 mins break_max_s) from 11:00 to 15:00
    t2 = datetime(2026, 11, 15, 15, 0, tzinfo=tz).astimezone(dt_timezone.utc)

    # Session 2: 15:00 to 17:00 (120 mins)
    s2_events = _generate_active_events(t2, duration_mins=120.0, step_s=60.0)

    metrics = compute_session_metrics(
        s1_events + s2_events,
        tz_name="Asia/Kolkata",
        break_max_s=10800.0,  # 3 hours
    )

    # Excluded from average break duration per spec section 2 & 6
    assert metrics["avg_break_duration_mins"] is None
    assert metrics["total_breaks_count"] == 0


def test_sessions_below_min_session_s():
    """Verify sessions shorter than min_session_s (120s) are ignored in session stats."""
    tz = zoneinfo.ZoneInfo("Asia/Kolkata")
    t1 = datetime(2026, 11, 15, 9, 0, tzinfo=tz).astimezone(dt_timezone.utc)

    # Candidate 1: 30 seconds (< 120s min_session_s)
    cand1 = [
        ActivityEvent(ts_utc=t1, kind=EventKind.KEY_CHAR),
        ActivityEvent(ts_utc=t1 + timedelta(seconds=30), kind=EventKind.KEY_CHAR),
    ]

    # Gap of 10 mins
    t2 = t1 + timedelta(minutes=10)

    # Candidate 2: 45 seconds (< 120s min_session_s)
    cand2 = [
        ActivityEvent(ts_utc=t2, kind=EventKind.KEY_CHAR),
        ActivityEvent(ts_utc=t2 + timedelta(seconds=45), kind=EventKind.KEY_CHAR),
    ]

    metrics = compute_session_metrics(
        cand1 + cand2,
        tz_name="Asia/Kolkata",
        min_session_s=120.0,
    )

    assert metrics["avg_session_duration_mins"] is None
    assert metrics["max_session_duration_mins"] is None
    assert metrics["extended_sessions_count"] is None
    assert metrics["total_breaks_count"] == 0


def test_focus_and_deep_work_blocks():
    """Verify focus blocks (>= 10 min) and deep work blocks (>= 25 min)."""
    tz = zoneinfo.ZoneInfo("Asia/Kolkata")
    t0 = datetime(2026, 11, 15, 9, 0, tzinfo=tz).astimezone(dt_timezone.utc)

    # Block 1: 15 mins (focus block, not deep work)
    b1_events = _generate_active_events(t0, duration_mins=15.0, step_s=30.0)

    # Gap of 150s (>= 120s focus_gap_s) interrupts focus block
    t_b2 = b1_events[-1].ts_utc + timedelta(seconds=150)

    # Block 2: 30 mins (focus block AND deep work block)
    b2_events = _generate_active_events(t_b2, duration_mins=30.0, step_s=30.0)

    metrics = compute_session_metrics(
        b1_events + b2_events,
        tz_name="Asia/Kolkata",
        focus_gap_s=120.0,
        focus_block_min=10.0,
        deep_work_min=25.0,
    )

    assert metrics["avg_focus_block_mins"] == pytest.approx((15.0 + 30.0) / 2.0)  # 22.5 mins
    assert metrics["max_focus_block_mins"] == pytest.approx(30.0)
    assert metrics["deep_work_blocks_count"] == 1  # Only the 30-min block >= 25 min
    assert metrics["total_focus_time_hours"] == pytest.approx(45.0 / 60.0)
