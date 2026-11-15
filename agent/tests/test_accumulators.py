"""Unit tests for keyboard and mouse building block accumulators (Spec Section 3).

Includes:
- Hand-computed calculations with detailed step-by-step arithmetic in comments.
- Empty window edge case.
- Single event edge cases.
- Mouse-only input window.
- Keyboard-only input window.
- Combined window accumulation.
"""
from datetime import datetime, timedelta, timezone
import pytest

from edc_schemas import ActivityEvent, EventKind, WindowBlocks
from edc_agent.collectors import (
    accumulate_keyboard,
    accumulate_mouse,
    accumulate_window_blocks,
)


def test_hand_calculation_keyboard():
    """Verify keyboard accumulator matches hand-computed expected values.

    === Hand Calculation Arithmetic Trace ===
    Reference timestamp T0 = 2026-11-15 10:00:00 UTC

    Events:
    k1:  KEY_CHAR      at T0 + 0.000s (0 ms)
    k2:  KEY_CHAR      at T0 + 0.150s (150 ms) -> flight 150 ms -> bin 100-200
    k3:  KEY_CHAR      at T0 + 0.350s (350 ms) -> flight 200 ms -> bin 200-300
    k4:  KEY_CHAR      at T0 + 0.600s (600 ms) -> flight 250 ms -> bin 200-300
    k5:  KEY_CHAR      at T0 + 0.900s (900 ms) -> flight 300 ms -> bin 300-500
    -> Bursts calculation:
       k1..k5 have 5 consecutive keys with all flight times <= 500 ms (150, 200, 250, 300).
       burst_min_keys = 5 -> Burst #1 detected! Length = 5.
       Next key is at 7.000s -> gap = 7.000 - 0.900 = 6.100s.
       6.100s >= 5.0s (long_silence_s) -> 1 long silence after burst!

    k6:  KEY_CHAR      at T0 + 7.000s (7000 ms)
         Flight from k5 is 6100 ms > 2000 ms (typing_gap_max_ms) -> excluded from flight times!
    k7:  KEY_CHAR      at T0 + 7.200s (7200 ms) -> flight 200 ms -> bin 200-300
    k8:  KEY_BACKSPACE at T0 + 7.800s (7800 ms) -> flight 600 ms -> bin 500-1000
         Correction run begins:
         Pause before correction = 7.800 - 7.200 = 600 ms (<= 10000 ms cap).
    k9:  KEY_BACKSPACE at T0 + 8.050s (8050 ms) -> flight 250 ms -> bin 200-300
    k10: KEY_BACKSPACE at T0 + 8.300s (8300 ms) -> flight 250 ms -> bin 200-300
    -> Backspace burst calculation:
       k8, k9, k10 are 3 consecutive backspaces with gaps <= 500 ms (250, 250).
       backspace_burst_min = 3 -> 1 backspace burst!
       1 correction run total.

    k11: KEY_CHAR      at T0 + 8.900s (8900 ms) -> flight 600 ms -> bin 500-1000
    k12: KEY_MODIFIER  at T0 + 9.000s (9000 ms) -> Modifier key ignored in flight times and counts!
    k13: KEY_CHAR      at T0 + 10.000s (10000 ms)
         Flight time from non-modifier k11 to k13 = 10.000 - 8.900 = 1100 ms -> bin 1000-2000
    k14: KEY_CHAR      at T0 + 10.200s (10200 ms) with key_up_ts = T0 + 10.280s (dwell = 80 ms)
         Flight from k13 to k14 = 200 ms -> bin 200-300

    --- Expected Totals ---
    Counts:
      n_char = 10 (k1, k2, k3, k4, k5, k6, k7, k11, k13, k14)
      n_backspace = 3 (k8, k9, k10)
      n_delete = 0
      n_other_key = 0

    Flight times:
      11 valid flight intervals:
      150 + 200 + 250 + 300 + 200 + 600 + 250 + 250 + 600 + 1100 + 200 = 4100.0 ms
      Sum of squares:
      150^2 + 200^2 + 250^2 + 300^2 + 200^2 + 600^2 + 250^2 + 250^2 + 600^2 + 1100^2 + 200^2
      = 22500 + 40000 + 62500 + 90000 + 40000 + 360000 + 62500 + 62500 + 360000 + 1210000 + 40000
      = 2,350,000.0 ms^2
      active_typing_s = 4100.0 / 1000.0 = 4.1 s

    Histogram bins:
      0_100:     0
      100_200:   1  (150)
      200_300:   6  (200, 250, 200, 250, 250, 200)
      300_500:   1  (300)
      500_1000:  2  (600, 600)
      1000_2000: 1  (1100)
      Total bins = 0 + 1 + 6 + 1 + 2 + 1 = 11

    Bursts:
      n_bursts = 1
      sum_burst_len = 5
      n_long_silences_after_burst = 1 (6.1s gap >= 5.0s)

    Corrections:
      n_correction_runs = 1
      n_backspace_bursts = 1
      sum_pause_before_correction_ms = 600.0

    Dwell:
      dwell_n = 1
      dwell_sum_ms = 80.0
      dwell_sum_sq_ms = 80^2 = 6400.0

    Active minutes:
      All events fall within 10:00 -> active_minutes = 1
    """
    t0 = datetime(2026, 11, 15, 10, 0, 0, tzinfo=timezone.utc)

    events = [
        # Burst 1 (5 keys, all flight times <= 500ms)
        ActivityEvent(ts_utc=t0 + timedelta(milliseconds=0), kind=EventKind.KEY_CHAR),
        ActivityEvent(ts_utc=t0 + timedelta(milliseconds=150), kind=EventKind.KEY_CHAR),
        ActivityEvent(ts_utc=t0 + timedelta(milliseconds=350), kind=EventKind.KEY_CHAR),
        ActivityEvent(ts_utc=t0 + timedelta(milliseconds=600), kind=EventKind.KEY_CHAR),
        ActivityEvent(ts_utc=t0 + timedelta(milliseconds=900), kind=EventKind.KEY_CHAR),
        # Long silence (6.1s)
        ActivityEvent(ts_utc=t0 + timedelta(milliseconds=7000), kind=EventKind.KEY_CHAR),
        ActivityEvent(ts_utc=t0 + timedelta(milliseconds=7200), kind=EventKind.KEY_CHAR),
        # Correction run with 3 backspaces (gap from k7 is 600ms, not a burst)
        ActivityEvent(ts_utc=t0 + timedelta(milliseconds=7800), kind=EventKind.KEY_BACKSPACE),
        ActivityEvent(ts_utc=t0 + timedelta(milliseconds=8050), kind=EventKind.KEY_BACKSPACE),
        ActivityEvent(ts_utc=t0 + timedelta(milliseconds=8300), kind=EventKind.KEY_BACKSPACE),
        # Post-correction typing
        ActivityEvent(ts_utc=t0 + timedelta(milliseconds=8900), kind=EventKind.KEY_CHAR),
        ActivityEvent(ts_utc=t0 + timedelta(milliseconds=9000), kind=EventKind.KEY_MODIFIER),
        ActivityEvent(ts_utc=t0 + timedelta(milliseconds=10000), kind=EventKind.KEY_CHAR),
        ActivityEvent(
            ts_utc=t0 + timedelta(milliseconds=10200),
            kind=EventKind.KEY_CHAR,
            key_up_ts=t0 + timedelta(milliseconds=10280),
        ),
    ]

    blocks = accumulate_keyboard(events, covered_s=900.0)

    # 1. Assert Key Counts
    assert blocks.n_char == 10
    assert blocks.n_backspace == 3
    assert blocks.n_delete == 0
    assert blocks.n_other_key == 0

    # 2. Assert Flight Times & Histogram
    assert blocks.flight_time_n == 11
    assert blocks.flight_time_sum_ms == pytest.approx(4100.0)
    assert blocks.flight_time_sum_sq_ms == pytest.approx(2350000.0)
    assert blocks.active_typing_s == pytest.approx(4.1)

    assert blocks.flight_bin_0_100 == 0
    assert blocks.flight_bin_100_200 == 1
    assert blocks.flight_bin_200_300 == 6
    assert blocks.flight_bin_300_500 == 1
    assert blocks.flight_bin_500_1000 == 2
    assert blocks.flight_bin_1000_2000 == 1

    # 3. Assert Bursts and Long Silences
    assert blocks.n_bursts == 1
    assert blocks.sum_burst_len == 5
    assert blocks.n_long_silences_after_burst == 1

    # 4. Assert Corrections
    assert blocks.n_correction_runs == 1
    assert blocks.n_backspace_bursts == 1
    assert blocks.sum_pause_before_correction_ms == pytest.approx(600.0)

    # 5. Assert Dwell Time
    assert blocks.dwell_n == 1
    assert blocks.dwell_sum_ms == pytest.approx(80.0)
    assert blocks.dwell_sum_sq_ms == pytest.approx(6400.0)

    # 6. Assert Active Minutes and Covered Time
    assert blocks.active_minutes == 1
    assert blocks.covered_s == 900.0


def test_hand_calculation_mouse():
    """Verify mouse accumulator matches hand-computed expected values.

    === Hand Calculation Arithmetic Trace ===
    Reference timestamp T0 = 2026-11-15 10:00:00 UTC

    1. Clicks & Double Click & Rapid Click:
       c1: MOUSE_CLICK at T0 + 1.000s, (100.0, 200.0), button 1
       c2: MOUSE_CLICK at T0 + 1.200s, (102.0, 201.0), button 1
           dt = 0.200s = 200ms <= 500ms
           dist = sqrt((102-100)^2 + (201-200)^2) = sqrt(4+1) = sqrt(5) ≈ 2.236 px <= 4.0 px
           -> Double click #1 detected!
       c3: MOUSE_CLICK at T0 + 1.500s, (102.0, 201.0), button 1
           Span c1..c3 = 1.500 - 1.000 = 0.500s <= 1.0s (rapid_click_s)
           rapid_click_n = 3 -> Rapid click run #1 detected!
       c4: MOUSE_CLICK at T0 + 4.500s, (300.0, 400.0), button 1
       c5: MOUSE_CLICK at T0 + 12.000s, (300.0, 400.0), button 1
           Gap from c4 to c5 = 7.5s > 5.0s (click_gap_max_s) -> excluded!

       Click intervals (<= 5.0s):
       c1 -> c2: 0.200 s
       c2 -> c3: 0.300 s
       c3 -> c4: 3.000 s
       n = 3
       sum = 0.2 + 0.3 + 3.0 = 3.500 s
       sum_sq = 0.2^2 + 0.3^2 + 3.0^2 = 0.04 + 0.09 + 9.0 = 9.130 s^2

    2. Pointer Moves, Speed, Accel, and Jump Filtering:
       bin size = 100ms (0.1s)
       m1: MOUSE_MOVE at T0 + 20.000s (bin 0), pos = (100.0, 100.0)
       m2: MOUSE_MOVE at T0 + 20.100s (bin 1), pos = (120.0, 100.0)
           Adjacent bin (dt = 0.1s)
           d1 = 20.0 px <= 3000 px
           speed v1 = 20.0 / 0.1 = 200.0 px/s
           Moving bin #1!
       m3: MOUSE_MOVE at T0 + 20.200s (bin 2), pos = (150.0, 100.0)
           Adjacent bin (dt = 0.1s)
           d2 = 30.0 px <= 3000 px
           speed v2 = 30.0 / 0.1 = 300.0 px/s
           Moving bin #2!
           Acceleration across consecutive moving bins:
           accel1 = |v2 - v1| / 0.1 = |300.0 - 200.0| / 0.1 = 100.0 / 0.1 = 1000.0 px/s^2
       m4: MOUSE_MOVE at T0 + 20.300s (bin 3), pos = (5000.0, 100.0)
           Distance d = 5000.0 - 150.0 = 4850.0 px > 3000 px (mouse_jump_px)
           -> Excessive Jump! Bin dropped from moving bins and speed calculation.

       Pointer totals:
       n_moving_bins = 2
       sum_speed_px_s = 200.0 + 300.0 = 500.0 px/s
       n_accel_samples = 1
       sum_abs_accel_px_s2 = 1000.0 px/s^2

    3. Scroll Ticks and Reversals:
       s1: MOUSE_SCROLL at T0 + 30.000s, scroll_ticks = 3 (direction +1)
       s2: MOUSE_SCROLL at T0 + 32.000s, scroll_ticks = -2 (direction -1)
           dt = 2.0s <= 5.0s -> Reversal #1!
       s3: MOUSE_SCROLL at T0 + 33.500s, scroll_ticks = 4 (direction +1)
           dt = 1.5s <= 5.0s -> Reversal #2!
       s4: MOUSE_SCROLL at T0 + 40.000s, scroll_ticks = -1 (direction -1)
           dt = 6.5s > 5.0s -> Not a rapid reversal!

       Scroll totals:
       n_scroll_ticks_abs = |3| + |-2| + |4| + |-1| = 3 + 2 + 4 + 1 = 10
       n_scroll_reversals = 2
    """
    t0 = datetime(2026, 11, 15, 10, 0, 0, tzinfo=timezone.utc)

    events = [
        # Clicks
        ActivityEvent(ts_utc=t0 + timedelta(milliseconds=1000), kind=EventKind.MOUSE_CLICK, x=100.0, y=200.0, button=1),
        ActivityEvent(ts_utc=t0 + timedelta(milliseconds=1200), kind=EventKind.MOUSE_CLICK, x=102.0, y=201.0, button=1),
        ActivityEvent(ts_utc=t0 + timedelta(milliseconds=1500), kind=EventKind.MOUSE_CLICK, x=102.0, y=201.0, button=1),
        ActivityEvent(ts_utc=t0 + timedelta(milliseconds=4500), kind=EventKind.MOUSE_CLICK, x=300.0, y=400.0, button=1),
        ActivityEvent(ts_utc=t0 + timedelta(milliseconds=12000), kind=EventKind.MOUSE_CLICK, x=300.0, y=400.0, button=1),
        # Pointer moves
        ActivityEvent(ts_utc=t0 + timedelta(milliseconds=20000), kind=EventKind.MOUSE_MOVE, x=100.0, y=100.0),
        ActivityEvent(ts_utc=t0 + timedelta(milliseconds=20100), kind=EventKind.MOUSE_MOVE, x=120.0, y=100.0),
        ActivityEvent(ts_utc=t0 + timedelta(milliseconds=20200), kind=EventKind.MOUSE_MOVE, x=150.0, y=100.0),
        ActivityEvent(ts_utc=t0 + timedelta(milliseconds=20300), kind=EventKind.MOUSE_MOVE, x=5000.0, y=100.0),  # Jump!
        # Scroll ticks
        ActivityEvent(ts_utc=t0 + timedelta(milliseconds=30000), kind=EventKind.MOUSE_SCROLL, scroll_ticks=3),
        ActivityEvent(ts_utc=t0 + timedelta(milliseconds=32000), kind=EventKind.MOUSE_SCROLL, scroll_ticks=-2),
        ActivityEvent(ts_utc=t0 + timedelta(milliseconds=33500), kind=EventKind.MOUSE_SCROLL, scroll_ticks=4),
        ActivityEvent(ts_utc=t0 + timedelta(milliseconds=40000), kind=EventKind.MOUSE_SCROLL, scroll_ticks=-1),
    ]

    blocks = accumulate_mouse(events, display_scale=1.25, covered_s=900.0)

    # 1. Assert Clicks, Double Clicks, Rapid Runs
    assert blocks.n_clicks == 5
    assert blocks.n_double_clicks == 1
    assert blocks.n_rapid_click_runs == 1
    assert blocks.click_interval_n == 3
    assert blocks.click_interval_sum_s == pytest.approx(3.5)
    assert blocks.click_interval_sum_sq_s == pytest.approx(9.13)

    # 2. Assert Pointer Movement, Speeds, Accel, and Display Scale
    assert blocks.n_moving_bins == 2
    assert blocks.sum_speed_px_s == pytest.approx(500.0)
    assert blocks.n_accel_samples == 1
    assert blocks.sum_abs_accel_px_s2 == pytest.approx(1000.0)
    assert blocks.display_scale == 1.25

    # 3. Assert Scrolls & Reversals
    assert blocks.n_scroll_ticks_abs == 10
    assert blocks.n_scroll_reversals == 2

    # 4. Assert Active Minutes and Covered Time
    assert blocks.active_minutes == 1
    assert blocks.covered_s == 900.0


def test_empty_window():
    """Verify empty event list produces clean zero-initialized WindowBlocks."""
    kb_blocks = accumulate_keyboard([])
    assert kb_blocks.n_char == 0
    assert kb_blocks.n_backspace == 0
    assert kb_blocks.flight_time_n == 0
    assert kb_blocks.flight_time_sum_ms == 0.0
    assert kb_blocks.active_typing_s == 0.0
    assert kb_blocks.active_minutes == 0
    assert kb_blocks.n_bursts == 0
    assert kb_blocks.n_correction_runs == 0

    mouse_blocks = accumulate_mouse([])
    assert mouse_blocks.n_clicks == 0
    assert mouse_blocks.click_interval_n == 0
    assert mouse_blocks.n_moving_bins == 0
    assert mouse_blocks.sum_speed_px_s == 0.0
    assert mouse_blocks.n_scroll_ticks_abs == 0
    assert mouse_blocks.active_minutes == 0

    combined = accumulate_window_blocks([])
    assert combined.n_char == 0
    assert combined.n_clicks == 0
    assert combined.active_minutes == 0
    assert combined.idle_s == 0.0


def test_single_event_cases():
    """Verify single event produces valid counts with zero intervals."""
    t0 = datetime(2026, 11, 15, 10, 0, 0, tzinfo=timezone.utc)

    # 1. Single character key event
    single_key = [ActivityEvent(ts_utc=t0, kind=EventKind.KEY_CHAR)]
    kb_blocks = accumulate_keyboard(single_key)
    assert kb_blocks.n_char == 1
    assert kb_blocks.flight_time_n == 0
    assert kb_blocks.flight_time_sum_ms == 0.0
    assert kb_blocks.active_typing_s == 0.0
    assert kb_blocks.active_minutes == 1
    assert kb_blocks.n_bursts == 0
    assert kb_blocks.n_correction_runs == 0

    # 2. Single mouse click event
    single_click = [ActivityEvent(ts_utc=t0, kind=EventKind.MOUSE_CLICK, x=100.0, y=200.0, button=1)]
    mouse_blocks = accumulate_mouse(single_click)
    assert mouse_blocks.n_clicks == 1
    assert mouse_blocks.click_interval_n == 0
    assert mouse_blocks.n_moving_bins == 0
    assert mouse_blocks.n_double_clicks == 0
    assert mouse_blocks.active_minutes == 1

    # 3. Single modifier event (ignored in typing counts)
    single_mod = [ActivityEvent(ts_utc=t0, kind=EventKind.KEY_MODIFIER)]
    mod_blocks = accumulate_keyboard(single_mod)
    assert mod_blocks.n_char == 0
    assert mod_blocks.n_other_key == 0
    assert mod_blocks.active_minutes == 0  # Spec: modifier-only events do not count as active minutes


def test_window_with_only_mouse_input():
    """Verify window with only mouse events leaves keyboard metrics clean and zeroes."""
    t0 = datetime(2026, 11, 15, 10, 0, 0, tzinfo=timezone.utc)

    mouse_events = [
        ActivityEvent(ts_utc=t0, kind=EventKind.MOUSE_CLICK, button=1),
        ActivityEvent(ts_utc=t0 + timedelta(seconds=1), kind=EventKind.MOUSE_CLICK, button=1),
        ActivityEvent(ts_utc=t0 + timedelta(seconds=2), kind=EventKind.MOUSE_SCROLL, scroll_ticks=-3),
    ]

    # Running keyboard accumulator on mouse events produces zeroes
    kb_blocks = accumulate_keyboard(mouse_events)
    assert kb_blocks.n_char == 0
    assert kb_blocks.n_backspace == 0
    assert kb_blocks.flight_time_n == 0
    assert kb_blocks.active_minutes == 0

    # Running mouse accumulator computes mouse statistics
    mouse_blocks = accumulate_mouse(mouse_events)
    assert mouse_blocks.n_clicks == 2
    assert mouse_blocks.click_interval_n == 1
    assert mouse_blocks.click_interval_sum_s == pytest.approx(1.0)
    assert mouse_blocks.n_scroll_ticks_abs == 3
    assert mouse_blocks.active_minutes == 1

    # Combined window
    combined = accumulate_window_blocks(mouse_events)
    assert combined.n_char == 0
    assert combined.n_clicks == 2
    assert combined.n_scroll_ticks_abs == 3
    assert combined.active_minutes == 1


def test_window_with_only_keyboard_input():
    """Verify window with only keyboard events leaves mouse metrics clean and zeroes."""
    t0 = datetime(2026, 11, 15, 10, 0, 0, tzinfo=timezone.utc)

    kb_events = [
        ActivityEvent(ts_utc=t0, kind=EventKind.KEY_CHAR),
        ActivityEvent(ts_utc=t0 + timedelta(milliseconds=200), kind=EventKind.KEY_CHAR),
        ActivityEvent(ts_utc=t0 + timedelta(milliseconds=400), kind=EventKind.KEY_BACKSPACE),
    ]

    # Running mouse accumulator on keyboard events produces zeroes
    mouse_blocks = accumulate_mouse(kb_events)
    assert mouse_blocks.n_clicks == 0
    assert mouse_blocks.n_moving_bins == 0
    assert mouse_blocks.n_scroll_ticks_abs == 0
    assert mouse_blocks.active_minutes == 0

    # Running keyboard accumulator computes keyboard statistics
    kb_blocks = accumulate_keyboard(kb_events)
    assert kb_blocks.n_char == 2
    assert kb_blocks.n_backspace == 1
    assert kb_blocks.flight_time_n == 2
    assert kb_blocks.flight_time_sum_ms == pytest.approx(400.0)
    assert kb_blocks.active_minutes == 1


def test_combined_window_idle_seconds_and_distinct_active_minutes():
    """Verify combined window accumulation correctly unifies distinct active minutes and idle gaps."""
    # Minute 0: keyboard event
    # Minute 0: mouse event (same minute, should only count as 1 active minute!)
    # Minute 2: mouse event (2 active minutes total)
    # Gap of 75 seconds between events -> counts toward idle_s (idle_threshold_s = 60s)
    t0 = datetime(2026, 11, 15, 10, 0, 0, tzinfo=timezone.utc)

    events = [
        ActivityEvent(ts_utc=t0, kind=EventKind.KEY_CHAR),
        ActivityEvent(ts_utc=t0 + timedelta(seconds=10), kind=EventKind.MOUSE_CLICK, button=1),
        # Gap of 75 seconds: 10:00:10 to 10:01:25
        ActivityEvent(ts_utc=t0 + timedelta(seconds=85), kind=EventKind.MOUSE_MOVE, x=100.0, y=100.0),
    ]

    combined = accumulate_window_blocks(events, idle_threshold_s=60.0)

    # 1. Distinct calendar minutes: 10:00 (has events at :00 and :10) and 10:01 (has event at :85) -> 2 active minutes
    assert combined.active_minutes == 2

    # 2. Idle seconds: 85 - 10 = 75.0s (>= 60s) -> idle_s = 75.0s
    assert combined.idle_s == pytest.approx(75.0)

    assert combined.n_char == 1
    assert combined.n_clicks == 1
