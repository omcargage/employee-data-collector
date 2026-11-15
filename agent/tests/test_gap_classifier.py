"""Tests for gap classification and heartbeat monitoring per docs/metrics_spec.md Section 1."""
from datetime import datetime, timedelta, timezone
import time
import pytest

from edc_agent.collectors.gap_classifier import (
    GapType,
    HeartbeatManager,
    classify_gap,
)
from edc_agent.platforms.windows.system_state import (
    SystemState,
    SystemStateEvent,
    WindowsSystemStateMonitor,
)
from edc_agent.storage.database import Database


def test_lunch_with_laptop_locked_away():
    """Synthetic timeline 1: Employee locks laptop for lunch.

    12:30: Last input event before lunch.
    12:31: Laptop locked (SystemState.LOCK).
    13:15: Laptop unlocked (SystemState.UNLOCK).
    13:16: First input event after lunch.
    Result: Gap [12:30, 13:16] must be classified as AWAY.
    """
    t_1230 = datetime(2026, 11, 15, 7, 0, tzinfo=timezone.utc)   # 12:30 IST
    t_1231 = datetime(2026, 11, 15, 7, 1, tzinfo=timezone.utc)   # 12:31 IST
    t_1315 = datetime(2026, 11, 15, 7, 45, tzinfo=timezone.utc)  # 13:15 IST
    t_1316 = datetime(2026, 11, 15, 7, 46, tzinfo=timezone.utc)  # 13:16 IST

    state_events = [
        SystemStateEvent(ts_utc=t_1231, state=SystemState.LOCK),
        SystemStateEvent(ts_utc=t_1315, state=SystemState.UNLOCK),
    ]

    result = classify_gap(
        gap_start=t_1230,
        gap_end=t_1316,
        state_events=state_events,
    )
    assert result == GapType.AWAY


def test_crash_mid_day_unknown():
    """Synthetic timeline 2: Agent crashes mid-day without OS sleep/lock.

    14:00: Last input event before crash.
    14:00:10: Last recorded agent heartbeat.
    14:40:00: Agent restarts after 40-minute outage.
    14:42:00: Next input event.
    Result: Gap [14:00, 14:42] must be classified as UNKNOWN (missing data, never zero).
    """
    t_1400 = datetime(2026, 11, 15, 8, 30, 0, tzinfo=timezone.utc)
    t_hb1 = datetime(2026, 11, 15, 8, 30, 10, tzinfo=timezone.utc)
    t_hb2 = datetime(2026, 11, 15, 9, 10, 0, tzinfo=timezone.utc)  # 40-min gap
    t_1442 = datetime(2026, 11, 15, 9, 12, 0, tzinfo=timezone.utc)

    heartbeats = [t_hb1, t_hb2]

    result = classify_gap(
        gap_start=t_1400,
        gap_end=t_1442,
        state_events=[],  # No sleep/lock reported
        heartbeats=heartbeats,
        max_heartbeat_gap_s=25.0,
    )
    assert result == GapType.UNKNOWN


def test_normal_idle():
    """Synthetic timeline 3: User stares at screen / reads document without input.

    11:00: Last input event.
    11:08: Next input event (8-minute gap).
    Agent runs continuously with steady heartbeats every 10s.
    Result: Gap [11:00, 11:08] must be classified as IDLE.
    """
    t_1100 = datetime(2026, 11, 15, 5, 30, tzinfo=timezone.utc)
    t_1108 = datetime(2026, 11, 15, 5, 38, tzinfo=timezone.utc)

    # Steady heartbeats every 10 seconds throughout the 8 minutes
    heartbeats = [
        t_1100 + timedelta(seconds=i * 10)
        for i in range(49)  # 0 to 480 seconds
    ]

    result = classify_gap(
        gap_start=t_1100,
        gap_end=t_1108,
        state_events=[],
        heartbeats=heartbeats,
    )
    assert result == GapType.IDLE


def test_system_suspend_resume_classified_as_away():
    """Verify system sleep/suspend transition classifies the gap as AWAY."""
    t_start = datetime(2026, 11, 15, 6, 0, tzinfo=timezone.utc)
    t_suspend = datetime(2026, 11, 15, 6, 5, tzinfo=timezone.utc)
    t_resume = datetime(2026, 11, 15, 6, 35, tzinfo=timezone.utc)
    t_end = datetime(2026, 11, 15, 6, 36, tzinfo=timezone.utc)

    state_events = [
        SystemStateEvent(ts_utc=t_suspend, state=SystemState.SUSPEND),
        SystemStateEvent(ts_utc=t_resume, state=SystemState.RESUME),
    ]

    result = classify_gap(gap_start=t_start, gap_end=t_end, state_events=state_events)
    assert result == GapType.AWAY


def test_heartbeat_manager_sqlite_integration():
    """Verify HeartbeatManager writes timestamps to SQLite agent_state and tracks history."""
    db = Database(":memory:")
    mgr = HeartbeatManager(db=db, interval_s=0.05)

    # Record explicit heartbeat
    ts = mgr.record_heartbeat()
    conn = db.get_connection()
    row = conn.execute("SELECT key, value FROM agent_state WHERE key = 'last_heartbeat';").fetchone()
    assert row is not None
    assert row["value"] == ts.isoformat()

    # Run background timer
    mgr.start()
    time.sleep(0.15)
    mgr.stop()

    heartbeats = mgr.get_heartbeats()
    assert len(heartbeats) >= 2


def test_windows_system_state_monitor_lifecycle():
    """Verify WindowsSystemStateMonitor registers, starts, and stops cleanly."""
    received = []
    monitor = WindowsSystemStateMonitor(callback=received.append)

    assert not monitor.is_running
    monitor.start()
    assert monitor.is_running

    # Emit a simulated test event
    now = datetime.now(timezone.utc)
    monitor.emit(SystemState.LOCK, ts_utc=now)
    assert len(received) == 1
    assert received[0].state == SystemState.LOCK
    assert received[0].ts_utc == now

    monitor.stop()
    assert not monitor.is_running
