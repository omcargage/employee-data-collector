"""Tests for the event pipeline: InputProvider interface, FakeInputProvider, and ActivityCollector."""
from datetime import datetime, timedelta, timezone
import time
import pytest

from edc_agent.collectors import ActivityCollector
from edc_agent.platforms.fake import FakeInputProvider
from edc_schemas import ActivityEvent, EventKind


def test_fake_input_provider_capabilities_and_lifecycle():
    """Verify FakeInputProvider exposes declared capabilities and lifecycle methods."""
    received = []
    provider = FakeInputProvider(
        callback=lambda e: received.append(e),
        capabilities={"key_dwell": True, "mouse_move": True},
    )
    caps = provider.get_capabilities()
    assert caps["key_dwell"] is True
    assert caps["mouse_move"] is True
    assert not provider.is_running

    # Add scripted events and replay
    now = datetime(2026, 11, 15, 10, 0, tzinfo=timezone.utc)
    ev1 = ActivityEvent(ts_utc=now, kind=EventKind.KEY_CHAR)
    ev2 = ActivityEvent(ts_utc=now + timedelta(seconds=1), kind=EventKind.KEY_BACKSPACE)
    provider.set_events([ev1, ev2])

    provider.start()
    time.sleep(0.05)
    provider.stop()

    assert len(received) == 2
    assert received[0].kind == EventKind.KEY_CHAR
    assert received[1].kind == EventKind.KEY_BACKSPACE


def test_scripted_stream_across_window_boundary_lands_in_right_windows():
    """Verify that events crossing a 15-minute window boundary land in their respective window accumulators."""
    tz = "Asia/Kolkata"
    collector = ActivityCollector(timezone_name=tz, max_queue_size=1000)
    collector.start()

    # Window A: 10:00 to 10:15 IST (04:30 to 04:45 UTC)
    # Window B: 10:15 to 10:30 IST (04:45 to 05:00 UTC)
    ts_w1_e1 = datetime(2026, 11, 15, 4, 32, 0, tzinfo=timezone.utc)
    ts_w1_e2 = datetime(2026, 11, 15, 4, 44, 59, tzinfo=timezone.utc)

    ts_w2_e1 = datetime(2026, 11, 15, 4, 45, 0, tzinfo=timezone.utc)
    ts_w2_e2 = datetime(2026, 11, 15, 4, 50, 0, tzinfo=timezone.utc)
    ts_w2_e3 = datetime(2026, 11, 15, 4, 59, 59, tzinfo=timezone.utc)

    scripted_events = [
        ActivityEvent(ts_utc=ts_w1_e1, kind=EventKind.KEY_CHAR),
        ActivityEvent(ts_utc=ts_w1_e2, kind=EventKind.MOUSE_MOVE, x=100.0, y=200.0),
        ActivityEvent(ts_utc=ts_w2_e1, kind=EventKind.KEY_DELETE),
        ActivityEvent(ts_utc=ts_w2_e2, kind=EventKind.MOUSE_CLICK, button=1),
        ActivityEvent(ts_utc=ts_w2_e3, kind=EventKind.KEY_OTHER),
    ]

    provider = FakeInputProvider(callback=collector.on_event, events=scripted_events)
    provider.replay_sync()

    # Allow worker thread to drain
    collector.stop(drain=True)

    accumulators = collector.get_all_accumulators()
    assert len(accumulators) == 2, f"Expected 2 windows, got {len(accumulators)}"

    # Identify window bounds
    bounds_w1 = (
        datetime(2026, 11, 15, 4, 30, tzinfo=timezone.utc),
        datetime(2026, 11, 15, 4, 45, tzinfo=timezone.utc),
    )
    bounds_w2 = (
        datetime(2026, 11, 15, 4, 45, tzinfo=timezone.utc),
        datetime(2026, 11, 15, 5, 0, tzinfo=timezone.utc),
    )

    acc_w1 = collector.get_accumulator(bounds_w1)
    acc_w2 = collector.get_accumulator(bounds_w2)

    assert acc_w1 is not None, f"Window 1 accumulator missing for {bounds_w1}"
    assert acc_w2 is not None, f"Window 2 accumulator missing for {bounds_w2}"

    assert acc_w1.event_count == 2
    assert acc_w1.events[0].ts_utc == ts_w1_e1
    assert acc_w1.events[1].ts_utc == ts_w1_e2

    assert acc_w2.event_count == 3
    assert acc_w2.events[0].ts_utc == ts_w2_e1
    assert acc_w2.events[1].ts_utc == ts_w2_e2
    assert acc_w2.events[2].ts_utc == ts_w2_e3


def test_flood_of_events_drops_oldest_without_blocking_producer():
    """Verify that saturating the bounded queue drops oldest events and increments drop counter without blocking."""
    capacity = 10
    total_events = 50
    collector = ActivityCollector(timezone_name="Asia/Kolkata", max_queue_size=capacity)

    # Note: Worker is NOT started yet, simulating consumer backlog or frozen consumer
    base = datetime(2026, 11, 15, 4, 30, tzinfo=timezone.utc)
    events = [
        ActivityEvent(ts_utc=base + timedelta(milliseconds=i * 10), kind=EventKind.KEY_CHAR)
        for i in range(total_events)
    ]

    # Producer floods the queue
    start_t = time.perf_counter()
    for ev in events:
        collector.on_event(ev)
    elapsed = time.perf_counter() - start_t

    # Producer must finish instantaneously without waiting on capacity
    assert elapsed < 0.2, f"Producer was blocked! Took {elapsed}s"

    # Queue must be at max capacity
    assert collector.queue_size == capacity
    # Total drops must exactly equal (total_events - capacity)
    expected_drops = total_events - capacity  # 50 - 10 = 40 drops
    assert collector.dropped_events_count == expected_drops

    # Drain and process remaining events
    collector.stop(drain=True)

    # Remaining events must be the newest 10 events (indices 40 to 49)
    bounds = (
        datetime(2026, 11, 15, 4, 30, tzinfo=timezone.utc),
        datetime(2026, 11, 15, 4, 45, tzinfo=timezone.utc),
    )
    acc = collector.get_accumulator(bounds)
    assert acc is not None
    assert acc.event_count == capacity

    # Verify that the events kept are the last 10 emitted
    assert acc.events[0].ts_utc == events[40].ts_utc
    assert acc.events[-1].ts_utc == events[49].ts_utc
