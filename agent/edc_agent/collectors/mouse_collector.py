"""Pure accumulator transforming ActivityEvents into mouse WindowBlocks per Spec Section 3.

Computes exact additive building blocks:
- Click counts, double clicks, rapid click runs.
- Click intervals (n, sum, sum_sq for gaps <= 5.0s).
- Scroll ticks and scroll reversals (direction changes within 5.0s).
- Pointer movement bins:
  - Sampled/binned per mouse_bin_ms (default 100ms).
  - Jumps > mouse_jump_px (default 3000px) dropped.
  - Moving bins count (n_moving_bins) and sum of speeds (sum_speed_px_s).
  - Acceleration across consecutive moving bins (n_accel_samples, sum_abs_accel_px_s2).
  - Display scale factor recorded alongside.
- Active minutes and idle seconds.
"""
from datetime import datetime, timezone
import math
from typing import Dict, List, Optional, Sequence, Set, Tuple

from edc_schemas import ActivityEvent, EventKind, WindowBlocks


def accumulate_mouse(
    events: Sequence[ActivityEvent],
    *,
    mouse_bin_ms: float = 100.0,
    mouse_jump_px: float = 3000.0,
    display_scale: float = 1.0,
    double_click_ms: float = 500.0,
    double_click_px: float = 4.0,
    rapid_click_n: int = 3,
    rapid_click_s: float = 1.0,
    click_gap_max_s: float = 5.0,
    scroll_reversal_window_s: float = 5.0,
    covered_s: float = 0.0,
    idle_threshold_s: float = 60.0,
) -> WindowBlocks:
    """Turn a list of ActivityEvents into a mouse WindowBlocks building block instance.

    Pure function over plain data. No I/O, no side effects.
    """
    # Filter for mouse events and sort chronologically
    mouse_events = [
        ev for ev in events
        if ev.kind in (EventKind.MOUSE_CLICK, EventKind.MOUSE_MOVE, EventKind.MOUSE_SCROLL)
    ]
    mouse_events.sort(key=lambda ev: ev.ts_utc)

    # 1. Active minutes: calendar minutes containing at least one mouse event
    active_minute_set: Set[Tuple[int, int, int, int, int]] = set()
    for ev in mouse_events:
        dt = ev.ts_utc
        active_minute_set.add((dt.year, dt.month, dt.day, dt.hour, dt.minute))
    active_minutes = len(active_minute_set)

    # 2. Clicks, Double Clicks, Rapid Click Runs, and Click Intervals
    click_events = [ev for ev in mouse_events if ev.kind == EventKind.MOUSE_CLICK]
    n_clicks = len(click_events)

    # Click intervals (gaps <= click_gap_max_s)
    click_interval_n = 0
    click_interval_sum_s = 0.0
    click_interval_sum_sq_s = 0.0

    for i in range(len(click_events) - 1):
        dt_s = (click_events[i + 1].ts_utc - click_events[i].ts_utc).total_seconds()
        if 0.0 <= dt_s <= click_gap_max_s:
            click_interval_n += 1
            click_interval_sum_s += dt_s
            click_interval_sum_sq_s += dt_s * dt_s

    # Double clicks: consecutive clicks on same button within double_click_ms and <= double_click_px
    n_double_clicks = 0
    i = 0
    while i < len(click_events) - 1:
        c1 = click_events[i]
        c2 = click_events[i + 1]
        dt_ms = (c2.ts_utc - c1.ts_utc).total_seconds() * 1000.0

        is_same_button = (c1.button == c2.button) or (c1.button is None or c2.button is None)
        if 0.0 <= dt_ms <= double_click_ms and is_same_button:
            dx = (c2.x or 0.0) - (c1.x or 0.0)
            dy = (c2.y or 0.0) - (c1.y or 0.0)
            dist = math.hypot(dx, dy)
            if dist <= double_click_px:
                n_double_clicks += 1
                i += 2  # Consume both clicks in this double click
                continue
        i += 1

    # Rapid click runs: sequences where >= rapid_click_n clicks occur within rapid_click_s
    n_rapid_click_runs = 0
    in_rapid_run = False
    k = 0
    while k <= len(click_events) - rapid_click_n:
        window_span = (click_events[k + rapid_click_n - 1].ts_utc - click_events[k].ts_utc).total_seconds()
        if window_span <= rapid_click_s:
            if not in_rapid_run:
                n_rapid_click_runs += 1
                in_rapid_run = True
            # Advance past rapid cluster
            k += 1
            while k < len(click_events):
                gap = (click_events[k].ts_utc - click_events[k - 1].ts_utc).total_seconds()
                if gap <= (rapid_click_s / (rapid_click_n - 1)):
                    k += 1
                else:
                    in_rapid_run = False
                    break
        else:
            in_rapid_run = False
            k += 1

    # 3. Scroll ticks and scroll direction reversals
    scroll_events = [ev for ev in mouse_events if ev.kind == EventKind.MOUSE_SCROLL]
    n_scroll_ticks_abs = sum(abs(ev.scroll_ticks or 0) for ev in scroll_events)

    n_scroll_reversals = 0
    last_dir: Optional[int] = None
    last_scroll_ts: Optional[datetime] = None

    for ev in scroll_events:
        ticks = ev.scroll_ticks or 0
        if ticks == 0:
            continue
        cur_dir = 1 if ticks > 0 else -1
        if last_dir is not None and cur_dir != last_dir:
            if last_scroll_ts is not None:
                elapsed_s = (ev.ts_utc - last_scroll_ts).total_seconds()
                if 0.0 <= elapsed_s <= scroll_reversal_window_s:
                    n_scroll_reversals += 1
        last_dir = cur_dir
        last_scroll_ts = ev.ts_utc

    # 4. Pointer movement: bins, speed, acceleration, and jump filtering
    pointer_events = [
        ev for ev in mouse_events
        if ev.x is not None and ev.y is not None and ev.kind == EventKind.MOUSE_MOVE
    ]

    n_moving_bins = 0
    sum_speed_px_s = 0.0
    n_accel_samples = 0
    sum_abs_accel_px_s2 = 0.0

    if len(pointer_events) >= 2:
        bin_size_s = mouse_bin_ms / 1000.0
        t0 = pointer_events[0].ts_utc

        # Bucket events into discrete time bins of width mouse_bin_ms
        # In each bin, keep the final pointer position.
        # Use millisecond rounding to avoid IEEE 754 float division floor errors (e.g. 0.3 // 0.1 == 2.0).
        bins_dict: Dict[int, ActivityEvent] = {}
        for ev in pointer_events:
            dt_ms = (ev.ts_utc - t0).total_seconds() * 1000.0
            b_idx = int(round(dt_ms / mouse_bin_ms))
            bins_dict[b_idx] = ev  # Latest position in bin

        sorted_bins = sorted(bins_dict.keys())

        last_pos_x = bins_dict[sorted_bins[0]].x or 0.0
        last_pos_y = bins_dict[sorted_bins[0]].y or 0.0
        last_bin_idx = sorted_bins[0]
        last_bin_speed: Optional[float] = None
        last_moving_bin_idx: Optional[int] = None

        for b_idx in sorted_bins[1:]:
            cur_ev = bins_dict[b_idx]
            cur_x = cur_ev.x or 0.0
            cur_y = cur_ev.y or 0.0

            dx = cur_x - last_pos_x
            dy = cur_y - last_pos_y
            dist = math.hypot(dx, dy)

            # Check for excessive jumps (monitor switch, remote desktop)
            if dist > mouse_jump_px:
                # Drop bin
                last_pos_x = cur_x
                last_pos_y = cur_y
                last_bin_idx = b_idx
                last_bin_speed = None
                last_moving_bin_idx = None
                continue

            # Pointer moved in this bin
            if dist > 0.0:
                dt_bins = b_idx - last_bin_idx
                dt_s = dt_bins * bin_size_s if dt_bins > 0 else bin_size_s
                speed = dist / dt_s

                n_moving_bins += 1
                sum_speed_px_s += speed

                # Acceleration across consecutive moving bins
                # Occurs when the immediately preceding bin was also a moving bin
                if last_moving_bin_idx is not None and b_idx == (last_moving_bin_idx + 1):
                    if last_bin_speed is not None:
                        accel = abs(speed - last_bin_speed) / bin_size_s
                        n_accel_samples += 1
                        sum_abs_accel_px_s2 += accel

                last_bin_speed = speed
                last_moving_bin_idx = b_idx
            else:
                last_bin_speed = None
                last_moving_bin_idx = None

            last_pos_x = cur_x
            last_pos_y = cur_y
            last_bin_idx = b_idx

    # 5. Idle seconds (gaps >= idle_threshold_s)
    idle_s = 0.0
    for i in range(len(mouse_events) - 1):
        gap = (mouse_events[i + 1].ts_utc - mouse_events[i].ts_utc).total_seconds()
        if gap >= idle_threshold_s:
            idle_s += gap

    return WindowBlocks(
        n_clicks=n_clicks,
        n_double_clicks=n_double_clicks,
        n_rapid_click_runs=n_rapid_click_runs,
        n_scroll_ticks_abs=n_scroll_ticks_abs,
        n_scroll_reversals=n_scroll_reversals,
        click_interval_n=click_interval_n,
        click_interval_sum_s=click_interval_sum_s,
        click_interval_sum_sq_s=click_interval_sum_sq_s,
        n_moving_bins=n_moving_bins,
        sum_speed_px_s=sum_speed_px_s,
        n_accel_samples=n_accel_samples,
        sum_abs_accel_px_s2=sum_abs_accel_px_s2,
        display_scale=display_scale,
        covered_s=covered_s,
        active_minutes=active_minutes,
        idle_s=idle_s,
    )
