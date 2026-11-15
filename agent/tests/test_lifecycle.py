"""Integration and unit tests for agent lifecycle, window closing, daily aggregation, and CLI control.

Validates:
1. FakeInputProvider simulating a full workday produces expected 15-minute and daily rollups.
2. Raw events are discarded from memory immediately after their window is aggregated.
3. Interrupted window restart recovery: marks low coverage, avoids double-counting.
4. Pause and resume via API and IPC commands (dropping events while paused).
5. Visible status line formatting and graceful shutdown.
"""
from datetime import date, datetime, timedelta, timezone as dt_timezone
import zoneinfo
import pytest

from edc_schemas import ActivityEvent, EventKind, Rollup15Min, RollupDaily
from edc_agent.config import EDCConfig
from edc_agent.lifecycle import AgentLifecycle
from edc_agent.platforms.fake import FakeInputProvider
from edc_agent.storage.database import Database


def _make_events(timestamps: list[datetime]) -> list[ActivityEvent]:
    """Helper generating keystroke events for given timestamps."""
    return [
        ActivityEvent(
            ts_utc=ts,
            kind=EventKind.KEY_CHAR,
        )
        for ts in timestamps
    ]


def test_workday_simulation_produces_15min_and_daily_rollups_and_discards_raw_events():
    """Verify that simulating a full workday produces both 15-minute and daily rollups in SQLite,

    and that raw events in the window accumulator are discarded after aggregation.
    """
    tz = zoneinfo.ZoneInfo("Asia/Kolkata")
    work_date = date(2026, 11, 16)  # Monday

    config = EDCConfig(
        timezone="Asia/Kolkata",
        shift_start="09:00",
        shift_end="18:00",
        lunch_window="12:30-13:15",
        logical_day_start="05:00",
    )
    db = Database(":memory:")

    # Prepare scripted events across the workday:
    # Morning: 09:00 to 12:30 IST (14 15-minute windows)
    t_start = datetime(2026, 11, 16, 9, 0, tzinfo=tz).astimezone(dt_timezone.utc)
    morning_timestamps = [t_start + timedelta(seconds=s) for s in range(0, 210 * 60 + 1, 30)]
    morning_events = _make_events(morning_timestamps)

    # Lunch break: 12:30 to 13:15 IST (45 minutes idle break)
    # Afternoon: 13:15 to 17:30 IST (17 15-minute windows)
    t_afternoon = datetime(2026, 11, 16, 13, 15, tzinfo=tz).astimezone(dt_timezone.utc)
    afternoon_timestamps = [t_afternoon + timedelta(seconds=s) for s in range(0, 255 * 60 + 1, 30)]
    afternoon_events = _make_events(afternoon_timestamps)

    all_day_events = morning_events + afternoon_events

    provider = FakeInputProvider(callback=lambda ev: None, events=all_day_events)

    lifecycle = AgentLifecycle(
        config=config,
        db=db,
        provider=provider,
        window_minutes=15,
    )
    provider.callback = lifecycle.on_event

    lifecycle.start(start_time_utc=t_start)

    # Feed events window-by-window and tick time forward
    # Day starts at 09:00 IST and ends after 18:00 IST
    cur_time = t_start
    end_of_day_utc = datetime(2026, 11, 16, 18, 0, tzinfo=tz).astimezone(dt_timezone.utc)
    next_day_boundary_utc = datetime(2026, 11, 17, 5, 1, tzinfo=tz).astimezone(dt_timezone.utc)

    # Group events by 15-minute intervals and simulate passage of time
    events_by_time = sorted(all_day_events, key=lambda ev: ev.ts_utc)
    ev_idx = 0
    total_ev = len(events_by_time)

    while cur_time <= next_day_boundary_utc:
        # Emit any events up to cur_time
        while ev_idx < total_ev and events_by_time[ev_idx].ts_utc <= cur_time:
            lifecycle.on_event(events_by_time[ev_idx])
            ev_idx += 1

        # Advance lifecycle tick
        lifecycle.tick(cur_time)
        cur_time += timedelta(minutes=15)

    # Trigger final boundary if needed
    lifecycle.tick(next_day_boundary_utc)

    # 1. Verify 15-minute rollups were created and stored in SQLite
    rollups_15min_count = db.get_rollups_15min_count()
    assert rollups_15min_count >= 30, f"Expected at least 30 windows, got {rollups_15min_count}"

    # Verify Rollup15Min schema adherence
    first_rollup = db.get_rollup_15min(1)
    assert first_rollup is not None
    assert isinstance(first_rollup, Rollup15Min)
    assert first_rollup.window_start is not None
    assert first_rollup.window_end is not None
    assert first_rollup.coverage_ratio >= 0.0

    # 2. Verify raw events were discarded from the collector
    # The collector accumulators for closed windows must be cleared
    accumulators = lifecycle.collector.get_all_accumulators()
    # At most 1 open window may remain
    assert len(accumulators) <= 1, f"Expected at most 1 active accumulator, got {len(accumulators)}"

    # 3. Verify Daily Rollup was created and stored in SQLite
    rollups_daily_count = db.get_rollups_daily_count()
    assert rollups_daily_count >= 1, f"Expected at least 1 daily rollup, got {rollups_daily_count}"

    daily_rollup = db.get_rollup_daily("2026-11-16")
    assert daily_rollup is not None
    assert isinstance(daily_rollup, RollupDaily)
    assert daily_rollup.logical_day == work_date
    assert daily_rollup.is_weekend is False
    assert daily_rollup.total_breaks_count >= 1
    assert daily_rollup.longest_lunch_break_mins == pytest.approx(45.0, abs=1.0)
    assert daily_rollup.lunch_skipped_flag is False

    lifecycle.stop()


def test_restart_recovery_marks_interrupted_window_low_coverage_and_prevents_double_counting():
    """Verify that an interrupted window from an abrupt crash/restart is recovered,

    marked low_coverage=True, and never double-counted.
    """
    db = Database(":memory:")
    tz = zoneinfo.ZoneInfo("Asia/Kolkata")
    config = EDCConfig(timezone="Asia/Kolkata", logical_day_start="05:00")

    # Simulate a crash: agent was running for window 10:00 - 10:15 UTC,
    # wrote active_window to agent_state, but crashed at 10:07 without closing the window.
    w_start = datetime(2026, 11, 16, 10, 0, tzinfo=dt_timezone.utc)
    w_end = datetime(2026, 11, 16, 10, 15, tzinfo=dt_timezone.utc)
    db.set_agent_state("active_window_start", w_start.isoformat())
    db.set_agent_state("active_window_end", w_end.isoformat())
    db.set_agent_state("status", "collecting")

    # Verify no rollup exists initially
    assert db.check_rollup_15min_exists(w_start.isoformat(), w_end.isoformat()) is False
    assert db.get_rollups_15min_count() == 0

    # Agent restarts at 10:20 (after window 10:00-10:15 has already elapsed)
    provider = FakeInputProvider(callback=lambda ev: None)
    lifecycle = AgentLifecycle(config=config, db=db, provider=provider, window_minutes=15)
    lifecycle.start(start_time_utc=datetime(2026, 11, 16, 10, 20, tzinfo=dt_timezone.utc))

    # Recovery must have recorded the interrupted window with low coverage
    assert db.check_rollup_15min_exists(w_start.isoformat(), w_end.isoformat()) is True
    assert db.get_rollups_15min_count() == 1

    interrupted = db.get_rollup_15min(1)
    assert interrupted is not None
    assert interrupted.window_start == w_start
    assert interrupted.window_end == w_end
    assert interrupted.low_coverage is True
    assert interrupted.coverage_ratio == 0.0

    # Advance time through another tick: Ensure no duplicate row is added for [10:00, 10:15]
    lifecycle.tick(datetime(2026, 11, 16, 10, 25, tzinfo=dt_timezone.utc))
    assert db.get_rollups_15min_count() == 1

    lifecycle.stop()


def test_status_line_and_pause_resume_via_commands():
    """Verify visible status line reflects states, and pause/resume correctly halts and resumes collection."""
    db = Database(":memory:")
    config = EDCConfig(timezone="Asia/Kolkata")
    provider = FakeInputProvider(callback=lambda ev: None)

    lifecycle = AgentLifecycle(config=config, db=db, provider=provider, window_minutes=15)
    provider.callback = lifecycle.on_event

    t_start = datetime(2026, 11, 16, 9, 0, tzinfo=dt_timezone.utc)
    lifecycle.start(start_time_utc=t_start)
    assert lifecycle.status == "collecting"
    assert "COLLECTING" in lifecycle.get_status_line()

    # Emit event while collecting -> accepted into collector accumulator
    t_ev = datetime(2026, 11, 16, 9, 5, tzinfo=dt_timezone.utc)
    lifecycle.on_event(ActivityEvent(ts_utc=t_ev, kind=EventKind.KEY_CHAR))
    lifecycle.collector.drain_sync()
    acc = lifecycle.collector.get_accumulator(lifecycle.current_window)
    assert acc is not None
    assert acc.event_count == 1

    # Pause via API
    lifecycle.pause()
    assert lifecycle.status == "paused"
    assert "PAUSED" in lifecycle.get_status_line()

    # Emit event while paused -> dropped!
    t_ev2 = datetime(2026, 11, 16, 9, 6, tzinfo=dt_timezone.utc)
    lifecycle.on_event(ActivityEvent(ts_utc=t_ev2, kind=EventKind.KEY_CHAR))
    lifecycle.collector.drain_sync()
    # Event count in accumulator must not have increased
    assert acc.event_count == 1

    # Resume via IPC command in SQLite
    db.set_agent_state("command", "resume")
    lifecycle.tick(datetime(2026, 11, 16, 9, 7, tzinfo=dt_timezone.utc))
    assert lifecycle.status == "collecting"
    assert "COLLECTING" in lifecycle.get_status_line()

    # Emit event after resume -> accepted
    t_ev3 = datetime(2026, 11, 16, 9, 8, tzinfo=dt_timezone.utc)
    lifecycle.on_event(ActivityEvent(ts_utc=t_ev3, kind=EventKind.KEY_CHAR))
    lifecycle.collector.drain_sync()
    assert acc.event_count == 2

    # Pause via IPC command in SQLite
    db.set_agent_state("command", "pause")
    lifecycle.tick(datetime(2026, 11, 16, 9, 9, tzinfo=dt_timezone.utc))
    assert lifecycle.status == "paused"
    assert "PAUSED" in lifecycle.get_status_line()

    lifecycle.stop()
    assert lifecycle.status == "stopped"
    assert db.get_agent_state("status") == "stopped"
