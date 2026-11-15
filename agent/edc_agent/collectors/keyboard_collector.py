"""Pure accumulator transforming ActivityEvents into keyboard WindowBlocks per Spec Section 3.

Computes exact additive building blocks:
- Key category counts: n_char, n_backspace, n_delete, n_other_key.
- Flight times (n, sum, sum_sq, histogram bins) for inter-key intervals <= typing_gap_max_ms.
- Bursts (>= burst_min_keys, flight <= burst_max_flight_ms) and following long silences (>= long_silence_s).
- Correction runs (gaps <= backspace_burst_gap_ms), backspace bursts, pause before correction (capped at 10s).
- Key dwell times (if key_up_ts provided).
- Active minutes and active_typing_s.
"""
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence, Set, Tuple

from edc_schemas import ActivityEvent, EventKind, WindowBlocks


def accumulate_keyboard(
    events: Sequence[ActivityEvent],
    *,
    typing_gap_max_ms: float = 2000.0,
    burst_min_keys: int = 5,
    burst_max_flight_ms: float = 500.0,
    long_silence_s: float = 5.0,
    backspace_burst_min: int = 3,
    backspace_burst_gap_ms: float = 500.0,
    covered_s: float = 0.0,
    idle_threshold_s: float = 60.0,
) -> WindowBlocks:
    """Turn a list of ActivityEvents into a keyboard WindowBlocks building block instance.

    Pure function over plain data. No I/O, no side effects.
    """
    # Filter for keyboard events and sort chronologically
    kb_events = [
        ev for ev in events
        if ev.kind in (
            EventKind.KEY_CHAR,
            EventKind.KEY_BACKSPACE,
            EventKind.KEY_DELETE,
            EventKind.KEY_OTHER,
            EventKind.KEY_MODIFIER,
        )
    ]
    kb_events.sort(key=lambda ev: ev.ts_utc)

    # 1. Counts of key categories (modifier keys are excluded from typing counts)
    n_char = sum(1 for ev in kb_events if ev.kind == EventKind.KEY_CHAR)
    n_backspace = sum(1 for ev in kb_events if ev.kind == EventKind.KEY_BACKSPACE)
    n_delete = sum(1 for ev in kb_events if ev.kind == EventKind.KEY_DELETE)
    n_other_key = sum(1 for ev in kb_events if ev.kind == EventKind.KEY_OTHER)

    # 2. Non-modifier keystrokes participate in flight times, bursts, and corrections
    non_mod_keys = [ev for ev in kb_events if ev.kind != EventKind.KEY_MODIFIER]

    # Active minutes: calendar minutes containing at least one non-modifier keystroke
    active_minute_set: Set[Tuple[int, int, int, int, int]] = set()
    for ev in non_mod_keys:
        dt = ev.ts_utc
        active_minute_set.add((dt.year, dt.month, dt.day, dt.hour, dt.minute))
    active_minutes = len(active_minute_set)

    # 3. Flight times (gaps between consecutive non-modifier keys <= typing_gap_max_ms)
    flight_time_n = 0
    flight_time_sum_ms = 0.0
    flight_time_sum_sq_ms = 0.0

    b0, b1, b2, b3, b4, b5 = 0, 0, 0, 0, 0, 0

    flight_intervals_ms: List[float] = []
    for i in range(len(non_mod_keys) - 1):
        dt_ms = (non_mod_keys[i + 1].ts_utc - non_mod_keys[i].ts_utc).total_seconds() * 1000.0
        flight_intervals_ms.append(dt_ms)
        if 0.0 <= dt_ms <= typing_gap_max_ms:
            flight_time_n += 1
            flight_time_sum_ms += dt_ms
            flight_time_sum_sq_ms += dt_ms * dt_ms

            if dt_ms < 100.0:
                b0 += 1
            elif dt_ms < 200.0:
                b1 += 1
            elif dt_ms < 300.0:
                b2 += 1
            elif dt_ms < 500.0:
                b3 += 1
            elif dt_ms < 1000.0:
                b4 += 1
            elif dt_ms <= 2000.0:
                b5 += 1

    active_typing_s = flight_time_sum_ms / 1000.0

    # 4. Typing Bursts and following long silences
    # A burst is a run of >= burst_min_keys consecutive non-modifier keys with flight times <= burst_max_flight_ms
    n_bursts = 0
    sum_burst_len = 0
    n_long_silences_after_burst = 0

    if len(non_mod_keys) >= burst_min_keys:
        current_burst_len = 1
        i = 0
        while i < len(non_mod_keys) - 1:
            dt_ms = flight_intervals_ms[i]
            if 0.0 <= dt_ms <= burst_max_flight_ms:
                current_burst_len += 1
                i += 1
            else:
                # Run ended
                if current_burst_len >= burst_min_keys:
                    n_bursts += 1
                    sum_burst_len += current_burst_len
                    # Check silence after burst
                    gap_after_s = dt_ms / 1000.0
                    if gap_after_s >= long_silence_s:
                        n_long_silences_after_burst += 1
                current_burst_len = 1
                i += 1

        # Check tail run
        if current_burst_len >= burst_min_keys:
            n_bursts += 1
            sum_burst_len += current_burst_len

    # 5. Correction runs and backspace bursts
    # Correction keys: backspace or delete.
    # Correction run: consecutive correction keys with gaps <= backspace_burst_gap_ms.
    # Pause before correction: gap between previous keystroke and first correction key (capped at 10s).
    # Backspace burst: >= backspace_burst_min consecutive backspaces with gaps <= backspace_burst_gap_ms.
    n_correction_runs = 0
    n_backspace_bursts = 0
    sum_pause_before_correction_ms = 0.0

    idx = 0
    while idx < len(non_mod_keys):
        ev = non_mod_keys[idx]
        if ev.kind in (EventKind.KEY_BACKSPACE, EventKind.KEY_DELETE):
            # Correction run starts
            first_corr_idx = idx
            if first_corr_idx > 0:
                pause_ms = (
                    non_mod_keys[first_corr_idx].ts_utc - non_mod_keys[first_corr_idx - 1].ts_utc
                ).total_seconds() * 1000.0
                if 0.0 <= pause_ms <= 10000.0:  # Pauses capped at 10s per spec
                    sum_pause_before_correction_ms += pause_ms

            # Traverse the correction run
            run_end_idx = first_corr_idx
            while run_end_idx < len(non_mod_keys) - 1:
                next_ev = non_mod_keys[run_end_idx + 1]
                if next_ev.kind not in (EventKind.KEY_BACKSPACE, EventKind.KEY_DELETE):
                    break
                gap_ms = (next_ev.ts_utc - non_mod_keys[run_end_idx].ts_utc).total_seconds() * 1000.0
                if gap_ms > backspace_burst_gap_ms:
                    break
                run_end_idx += 1

            n_correction_runs += 1

            # Check for backspace bursts within this correction sequence
            # (consecutive runs of >= backspace_burst_min backspaces with gaps <= backspace_burst_gap_ms)
            b_count = 0
            for k in range(first_corr_idx, run_end_idx + 1):
                if non_mod_keys[k].kind == EventKind.KEY_BACKSPACE:
                    b_count += 1
                else:
                    if b_count >= backspace_burst_min:
                        n_backspace_bursts += 1
                    b_count = 0
            if b_count >= backspace_burst_min:
                n_backspace_bursts += 1

            idx = run_end_idx + 1
        else:
            idx += 1

    # 6. Dwell time (if key_up_ts provided)
    dwell_n = 0
    dwell_sum_ms = 0.0
    dwell_sum_sq_ms = 0.0

    for ev in kb_events:
        if ev.key_up_ts is not None and ev.key_up_ts >= ev.ts_utc:
            d_ms = (ev.key_up_ts - ev.ts_utc).total_seconds() * 1000.0
            dwell_n += 1
            dwell_sum_ms += d_ms
            dwell_sum_sq_ms += d_ms * d_ms

    # 7. Idle seconds (input silence >= idle_threshold_s)
    idle_s = 0.0
    for i in range(len(kb_events) - 1):
        gap = (kb_events[i + 1].ts_utc - kb_events[i].ts_utc).total_seconds()
        if gap >= idle_threshold_s:
            idle_s += gap

    return WindowBlocks(
        n_char=n_char,
        n_backspace=n_backspace,
        n_delete=n_delete,
        n_other_key=n_other_key,
        flight_time_n=flight_time_n,
        flight_time_sum_ms=flight_time_sum_ms,
        flight_time_sum_sq_ms=flight_time_sum_sq_ms,
        flight_bin_0_100=b0,
        flight_bin_100_200=b1,
        flight_bin_200_300=b2,
        flight_bin_300_500=b3,
        flight_bin_500_1000=b4,
        flight_bin_1000_2000=b5,
        covered_s=covered_s,
        active_typing_s=active_typing_s,
        active_minutes=active_minutes,
        idle_s=idle_s,
        n_bursts=n_bursts,
        sum_burst_len=sum_burst_len,
        n_long_silences_after_burst=n_long_silences_after_burst,
        n_correction_runs=n_correction_runs,
        n_backspace_bursts=n_backspace_bursts,
        sum_pause_before_correction_ms=sum_pause_before_correction_ms,
        dwell_n=dwell_n,
        dwell_sum_ms=dwell_sum_ms,
        dwell_sum_sq_ms=dwell_sum_sq_ms,
    )
