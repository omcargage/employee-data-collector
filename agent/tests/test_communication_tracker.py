"""Unit tests for communication and messaging activity tracker (Option 2 desktop process heuristic)."""
from datetime import date, datetime, timedelta, timezone
from typing import Optional
import pytest

from edc_schemas import ActivityEvent, EventKind, RollupDaily, Rollup15Min
from edc_agent.collectors.communication_tracker import CommunicationTracker
from edc_agent.metrics.workhour_metrics import build_rollup_daily
from edc_agent.storage.database import Database
from edc_agent.config import EDCConfig
from edc_agent.lifecycle import AgentLifecycle
from edc_agent.platforms.fake import FakeInputProvider


def test_process_matching():
    """Verify detection of registered communication executables."""
    tracker = CommunicationTracker(
        comm_apps=["slack", "teams", "outlook", "discord"],
        process_getter=lambda: "slack.exe",
    )
    assert tracker.is_communication_process("slack.exe") is True
    assert tracker.is_communication_process("Slack") is True
    assert tracker.is_communication_process("teams.exe") is True
    assert tracker.is_communication_process("ms-teams.exe") is True
    assert tracker.is_communication_process("OUTLOOK.EXE") is True
    assert tracker.is_communication_process("discord.exe") is True

    # Non-communication apps
    assert tracker.is_communication_process("code.exe") is False
    assert tracker.is_communication_process("chrome.exe") is False
    assert tracker.is_communication_process("cmd.exe") is False
    assert tracker.is_communication_process(None) is False


def test_enter_key_in_comm_app_records_message():
    """Verify Enter keypress in communication app records a message timestamp."""
    current_proc: Optional[str] = "slack.exe"
    tracker = CommunicationTracker(
        process_getter=lambda: current_proc,
        cache_ttl_s=0.0,
    )

    t0 = datetime(2026, 11, 16, 10, 0, 0, tzinfo=timezone.utc)

    # 1. Type characters in Slack
    for i in range(5):
        tracker.on_event(ActivityEvent(ts_utc=t0 + timedelta(seconds=i), kind=EventKind.KEY_CHAR))

    assert len(tracker.message_events) == 0

    # 2. Press Enter in Slack -> message sent!
    tracker.on_event(
        ActivityEvent(
            ts_utc=t0 + timedelta(seconds=6),
            kind=EventKind.KEY_OTHER,
            is_enter=True,
        )
    )

    assert len(tracker.message_events) == 1
    assert tracker.message_events[0] == t0 + timedelta(seconds=6)


def test_debounce_rapid_repeated_enters():
    """Verify rapid repeated Enters (< 1.0s) debounce into a single message."""
    tracker = CommunicationTracker(
        process_getter=lambda: "teams.exe",
        cache_ttl_s=0.0,
    )

    t0 = datetime(2026, 11, 16, 14, 0, 0, tzinfo=timezone.utc)

    # Enter pressed three times in rapid succession (e.g. 0.2s intervals)
    tracker.on_event(ActivityEvent(ts_utc=t0, kind=EventKind.KEY_OTHER, is_enter=True))
    tracker.on_event(ActivityEvent(ts_utc=t0 + timedelta(milliseconds=200), kind=EventKind.KEY_OTHER, is_enter=True))
    tracker.on_event(ActivityEvent(ts_utc=t0 + timedelta(milliseconds=400), kind=EventKind.KEY_OTHER, is_enter=True))

    assert len(tracker.message_events) == 1


def test_typing_burst_and_window_switch_infers_message():
    """Verify typing burst in comm app followed by switching away records sent message."""
    active_proc = "outlook.exe"
    tracker = CommunicationTracker(
        process_getter=lambda: active_proc,
        cache_ttl_s=0.0,
    )

    t0 = datetime(2026, 11, 16, 11, 0, 0, tzinfo=timezone.utc)

    # Type 4 characters in Outlook
    for i in range(4):
        tracker.on_event(ActivityEvent(ts_utc=t0 + timedelta(seconds=i), kind=EventKind.KEY_CHAR))

    assert len(tracker.message_events) == 0

    # User switches to VS Code
    active_proc = "code.exe"
    tracker.on_event(ActivityEvent(ts_utc=t0 + timedelta(seconds=10), kind=EventKind.KEY_CHAR))

    assert len(tracker.message_events) == 1
    assert tracker.message_events[0] == t0 + timedelta(seconds=3)


def test_non_comm_app_activity_ignored():
    """Verify keyboard input in non-communication applications does not record messages."""
    tracker = CommunicationTracker(
        process_getter=lambda: "code.exe",
        cache_ttl_s=0.0,
    )

    t0 = datetime(2026, 11, 16, 12, 0, 0, tzinfo=timezone.utc)

    for i in range(10):
        tracker.on_event(ActivityEvent(ts_utc=t0 + timedelta(seconds=i), kind=EventKind.KEY_CHAR))
    tracker.on_event(ActivityEvent(ts_utc=t0 + timedelta(seconds=11), kind=EventKind.KEY_OTHER, is_enter=True))

    assert len(tracker.message_events) == 0


def test_daily_communication_metrics_calculation():
    """Verify classification of shift hours, after-hours, and late-night messages."""
    tracker = CommunicationTracker(process_getter=lambda: "slack.exe", cache_ttl_s=0.0)

    # Local timezone Asia/Kolkata (UTC + 05:30)
    # 04:30 UTC = 10:00 IST (Shift 09:00 - 18:00) -> Work hours
    # 14:00 UTC = 19:30 IST -> After hours
    # 17:45 UTC = 23:15 IST -> After hours AND Late night (22:00 - 05:00)
    msg1_utc = datetime(2026, 11, 16, 4, 30, 0, tzinfo=timezone.utc)
    msg2_utc = datetime(2026, 11, 16, 14, 0, 0, tzinfo=timezone.utc)
    msg3_utc = datetime(2026, 11, 16, 17, 45, 0, tzinfo=timezone.utc)

    tracker.record_message(msg1_utc)
    tracker.record_message(msg2_utc)
    tracker.record_message(msg3_utc)

    metrics = tracker.compute_daily_metrics(
        logical_day=date(2026, 11, 16),
        tz_name="Asia/Kolkata",
        shift_start="09:00",
        shift_end="18:00",
        late_night_window="22:00-05:00",
    )

    assert metrics["total_msgs_sent"] == 3
    assert metrics["msgs_sent_after_hours"] == 2
    assert metrics["msgs_sent_late_night"] == 1
    assert metrics["first_msg_time"] == "10:00"
    assert metrics["last_msg_time"] == "23:15"


def test_zero_messages_daily_metrics():
    """Verify null/zero rules when no messages are detected."""
    tracker = CommunicationTracker(process_getter=lambda: "slack.exe", cache_ttl_s=0.0)

    metrics = tracker.compute_daily_metrics(
        logical_day=date(2026, 11, 16),
        tz_name="Asia/Kolkata",
    )

    assert metrics["total_msgs_sent"] == 0
    assert metrics["msgs_sent_after_hours"] == 0
    assert metrics["msgs_sent_late_night"] == 0
    assert metrics["first_msg_time"] is None
    assert metrics["last_msg_time"] is None


def test_checkpoint_and_restore_with_database():
    """Verify message timestamps persist across tracker/agent restarts via agent_state."""
    db = Database(":memory:")
    proc = "slack.exe"
    tracker1 = CommunicationTracker(process_getter=lambda: proc, db=db, cache_ttl_s=0.0)

    t1 = datetime(2026, 11, 16, 5, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 11, 16, 6, 0, 0, tzinfo=timezone.utc)

    tracker1.record_message(t1)
    tracker1.record_message(t2)

    assert len(tracker1.message_events) == 2

    # Instantiate new tracker with same DB (simulating restart)
    tracker2 = CommunicationTracker(process_getter=lambda: proc, db=db, cache_ttl_s=0.0)
    assert len(tracker2.message_events) == 2
    assert tracker2.message_events[0] == t1
    assert tracker2.message_events[1] == t2

    # Reset day
    tracker2.reset_day()
    assert len(tracker2.message_events) == 0
    assert db.get_agent_state("comm_events_json") == ""


def test_build_rollup_daily_with_comm_metrics():
    """Verify build_rollup_daily stores validated communication metrics in RollupDaily."""
    day = date(2026, 11, 16)
    comm_metrics = {
        "total_msgs_sent": 8,
        "msgs_sent_after_hours": 3,
        "msgs_sent_late_night": 1,
        "first_msg_time": "09:15",
        "last_msg_time": "22:45",
    }

    t0 = datetime(2026, 11, 16, 4, 0, 0, tzinfo=timezone.utc)
    events = [ActivityEvent(ts_utc=t0 + timedelta(minutes=m), kind=EventKind.KEY_CHAR) for m in range(10)]

    daily = build_rollup_daily(
        logical_day=day,
        events=events,
        coverage_ratio=1.0,
        comm_metrics=comm_metrics,
        profile="engineering_core",
    )

    assert daily.total_msgs_sent == 8
    assert daily.msgs_sent_after_hours == 3
    assert daily.msgs_sent_late_night == 1
    assert daily.first_msg_time == "09:15"
    assert daily.last_msg_time == "22:45"
    assert daily.profile == "engineering_core"


def test_lifecycle_daily_close_stores_comm_metrics():
    """Verify AgentLifecycle._close_logical_day includes communication metrics in DB."""
    db = Database(":memory:")
    config = EDCConfig(timezone="Asia/Kolkata", shift_start="09:00", shift_end="18:00")
    lifecycle = AgentLifecycle(config=config, db=db, require_consent=False)

    # Mock communication tracker with an active message
    lifecycle.communication_tracker._get_process = lambda: "teams.exe"
    lifecycle.communication_tracker._cache_ttl_s = 0.0

    msg_utc = datetime(2026, 11, 16, 4, 30, 0, tzinfo=timezone.utc)
    lifecycle.communication_tracker.record_message(msg_utc)

    # Close logical day
    daily = lifecycle._close_logical_day(date(2026, 11, 16))
    assert daily is not None
    assert daily.total_msgs_sent == 1
    assert daily.first_msg_time == "10:00"

    # Verify retrieved from DB
    retrieved = db.get_rollup_daily("2026-11-16")
    assert retrieved is not None
    assert retrieved.total_msgs_sent == 1
    assert retrieved.first_msg_time == "10:00"
