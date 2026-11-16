"""Synthetic activity pattern generators for validation of the EDC metric pipeline.

Generates realistic ActivityEvent streams for:
- Fast typing vs. slow typing (WPM and flight time validation).
- Clean typing vs. heavy corrections (backspace/correction ratio validation).
- Calm mouse tracking vs. mouse jitter (velocity and distance validation).
"""
from datetime import datetime, timedelta, timezone
import math
import random
from typing import List, Optional

from edc_schemas import ActivityEvent, EventKind


def generate_typing_stream(
    target_wpm: float = 60.0,
    n_keystrokes: int = 150,
    correction_rate: float = 0.0,
    start_time: Optional[datetime] = None,
    seed: int = 42,
) -> List[ActivityEvent]:
    """Generate a synthetic keystroke stream targeting a specific typing speed (WPM).

    Standard WPM definition: 1 word = 5 characters (including spaces).
    Inter-keystroke interval = 60.0 / (target_wpm * 5) seconds.
    """
    rng = random.Random(seed)
    base_time = start_time or datetime(2026, 11, 17, 10, 0, tzinfo=timezone.utc)
    base_interval_s = 60.0 / (max(5.0, target_wpm) * 5.0)

    events: List[ActivityEvent] = []
    current_time = base_time

    for i in range(n_keystrokes):
        # Add slight natural jitter (+/- 15%)
        jitter = rng.uniform(-0.15, 0.15) * base_interval_s
        dt = max(0.02, base_interval_s + jitter)
        current_time += timedelta(seconds=dt)

        # Intermittently insert spaces every ~5 keystrokes
        if i > 0 and i % 5 == 0:
            kind = EventKind.KEY_CHAR
        elif correction_rate > 0.0 and rng.random() < correction_rate:
            # Correction event
            kind = EventKind.KEY_BACKSPACE
        else:
            kind = EventKind.KEY_CHAR

        events.append(ActivityEvent(ts_utc=current_time, kind=kind))

    return events


def generate_heavy_correction_stream(
    n_words: int = 30,
    start_time: Optional[datetime] = None,
    seed: int = 101,
) -> List[ActivityEvent]:
    """Generate a typing stream simulating heavy corrections and error bursts.

    Types 3-4 characters forward, then triggers multiple backspaces in rapid succession.
    """
    rng = random.Random(seed)
    base_time = start_time or datetime(2026, 11, 17, 10, 0, tzinfo=timezone.utc)
    current_time = base_time
    events: List[ActivityEvent] = []

    for _ in range(n_words):
        # Type forward 3 to 5 chars at normal speed (~50 WPM)
        for _ in range(rng.randint(3, 5)):
            current_time += timedelta(seconds=rng.uniform(0.18, 0.25))
            events.append(ActivityEvent(ts_utc=current_time, kind=EventKind.KEY_CHAR))

        # Heavy correction burst: 2 to 4 rapid backspaces
        for _ in range(rng.randint(2, 4)):
            current_time += timedelta(seconds=rng.uniform(0.08, 0.14))
            events.append(ActivityEvent(ts_utc=current_time, kind=EventKind.KEY_BACKSPACE))

    return events


def generate_mouse_jitter_stream(
    duration_s: float = 30.0,
    start_time: Optional[datetime] = None,
    sample_interval_s: float = 0.10,
    jitter_magnitude: float = 250.0,
    seed: int = 202,
) -> List[ActivityEvent]:
    """Generate high-frequency, erratic mouse movement events simulating mouse jitter."""
    rng = random.Random(seed)
    base_time = start_time or datetime(2026, 11, 17, 10, 0, tzinfo=timezone.utc)
    current_time = base_time
    events: List[ActivityEvent] = []

    x = 500.0
    y = 500.0
    elapsed = 0.0

    while elapsed < duration_s:
        current_time += timedelta(seconds=sample_interval_s)
        elapsed += sample_interval_s

        # Rapid erratic jumps in random directions
        angle = rng.uniform(0, 2 * math.pi)
        step = rng.uniform(jitter_magnitude * 0.6, jitter_magnitude * 1.4)
        x = max(0.0, min(1920.0, x + step * math.cos(angle)))
        y = max(0.0, min(1080.0, y + step * math.sin(angle)))

        events.append(
            ActivityEvent(
                ts_utc=current_time,
                kind=EventKind.MOUSE_MOVE,
                x=x,
                y=y,
            )
        )

        # Occasional rapid clicking during jitter
        if rng.random() < 0.20:
            events.append(
                ActivityEvent(
                    ts_utc=current_time + timedelta(milliseconds=10),
                    kind=EventKind.MOUSE_CLICK,
                    x=x,
                    y=y,
                )
            )

    return events


def generate_smooth_mouse_stream(
    duration_s: float = 30.0,
    start_time: Optional[datetime] = None,
    sample_interval_s: float = 0.10,
    linear_speed_px_s: float = 40.0,
) -> List[ActivityEvent]:
    """Generate smooth, calm, linear mouse movement events."""
    base_time = start_time or datetime(2026, 11, 17, 10, 0, tzinfo=timezone.utc)
    current_time = base_time
    events: List[ActivityEvent] = []

    x = 100.0
    y = 100.0
    elapsed = 0.0
    step_per_sample = linear_speed_px_s * sample_interval_s

    while elapsed < duration_s:
        current_time += timedelta(seconds=sample_interval_s)
        elapsed += sample_interval_s

        x = (x + step_per_sample) % 1800.0
        y = (y + (step_per_sample * 0.5)) % 1000.0

        events.append(
            ActivityEvent(
                ts_utc=current_time,
                kind=EventKind.MOUSE_MOVE,
                x=x,
                y=y,
            )
        )

    return events
