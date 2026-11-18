"""Collectors subpackage for capturing raw behavioural input events.

Gathers keyboard, mouse, and system activity events in-memory using platform input providers.
"""
from .activity_collector import ActivityCollector, WindowAccumulator
from .communication_tracker import CommunicationTracker
from .gap_classifier import GapType, HeartbeatManager, classify_gap
from .keyboard_collector import accumulate_keyboard
from .mouse_collector import accumulate_mouse


def accumulate_window_blocks(events, **kwargs):
    """Accumulates both keyboard and mouse events into a unified WindowBlocks instance."""
    from edc_schemas import EventKind, WindowBlocks

    covered_s = kwargs.get("covered_s", 0.0)
    idle_threshold_s = kwargs.get("idle_threshold_s", 60.0)
    display_scale = kwargs.get("display_scale", 1.0)

    kb_blocks = accumulate_keyboard(events, **{k: v for k, v in kwargs.items() if k in [
        "typing_gap_max_ms", "burst_min_keys", "burst_max_flight_ms",
        "long_silence_s", "backspace_burst_min", "backspace_burst_gap_ms",
        "covered_s", "idle_threshold_s"
    ]})
    mouse_blocks = accumulate_mouse(events, **{k: v for k, v in kwargs.items() if k in [
        "mouse_bin_ms", "mouse_jump_px", "display_scale",
        "double_click_ms", "double_click_px", "rapid_click_n",
        "rapid_click_s", "click_gap_max_s", "scroll_reversal_window_s",
        "covered_s", "idle_threshold_s"
    ]})

    merged = kb_blocks + mouse_blocks

    active_minute_set = set()
    for ev in events:
        if ev.kind != EventKind.KEY_MODIFIER:
            dt = ev.ts_utc
            active_minute_set.add((dt.year, dt.month, dt.day, dt.hour, dt.minute))

    sorted_events = sorted(events, key=lambda ev: ev.ts_utc)
    combined_idle_s = 0.0
    for i in range(len(sorted_events) - 1):
        gap = (sorted_events[i + 1].ts_utc - sorted_events[i].ts_utc).total_seconds()
        if gap >= idle_threshold_s:
            combined_idle_s += gap

    data = merged.model_dump()
    data["active_minutes"] = len(active_minute_set)
    data["idle_s"] = combined_idle_s
    data["covered_s"] = covered_s
    data["display_scale"] = display_scale
    return WindowBlocks(**data)


__all__ = [
    "ActivityCollector",
    "WindowAccumulator",
    "GapType",
    "classify_gap",
    "HeartbeatManager",
    "CommunicationTracker",
    "accumulate_keyboard",
    "accumulate_mouse",
    "accumulate_window_blocks",
]
