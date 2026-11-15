"""Pure functions computing 15-minute keyboard metrics from WindowBlocks per Spec Section 4.

Applies authoritative null rules:
- min_keystrokes: returns None if total_keystrokes < min_keystrokes (default 30) for WPM & ratios.
- min_flight_intervals: returns None if flight_time_n < min_flight_intervals (default 10) for flight mean/std/CV.
- key_dwell_capable: returns None if platform does not support reliable dwell time.
"""
import math
from typing import Any, Dict, Optional

from edc_schemas import WindowBlocks


def compute_keyboard_metrics(
    blocks: WindowBlocks,
    *,
    covered_s: Optional[float] = None,
    min_keystrokes: int = 30,
    min_flight_intervals: int = 10,
    key_dwell_capable: bool = False,
) -> Dict[str, Any]:
    """Compute 15-minute keyboard metrics from WindowBlocks building blocks.

    Pure function over plain data. Missing statistics return None, never 0.
    """
    effective_covered_s = covered_s if covered_s is not None else blocks.covered_s

    # 1. Basic counts (never null, 0 if no events)
    char_keystrokes = blocks.n_char
    backspace_count = blocks.n_backspace
    delete_count = blocks.n_delete
    other_count = blocks.n_other_key
    total_keystrokes = char_keystrokes + backspace_count + delete_count + other_count
    total_correction_keys = backspace_count + delete_count
    repeated_backspace_bursts = blocks.n_backspace_bursts

    # 2. Flight times (null rule: flight_time_n < min_flight_intervals)
    mean_flight_time_ms: Optional[float] = None
    flight_time_std_ms: Optional[float] = None
    keystroke_coefficient_of_variation: Optional[float] = None

    if blocks.flight_time_n >= min_flight_intervals:
        n = blocks.flight_time_n
        s = blocks.flight_time_sum_ms
        ss = blocks.flight_time_sum_sq_ms

        mean_flight_time_ms = s / n
        if n >= 2:
            variance = (ss - (s * s) / n) / (n - 1)
            flight_time_std_ms = math.sqrt(max(0.0, variance))
            if mean_flight_time_ms > 0.0:
                keystroke_coefficient_of_variation = flight_time_std_ms / mean_flight_time_ms

    # 3. Time ratios and speed
    active_typing_ratio: Optional[float] = None
    if effective_covered_s > 0.0:
        active_typing_ratio = blocks.active_typing_s / effective_covered_s

    keystrokes_per_second: Optional[float] = None
    if effective_covered_s > 0.0:
        keystrokes_per_second = total_keystrokes / effective_covered_s

    # 4. WPM and error ratios (null rule: total_keystrokes < min_keystrokes or active_typing_s == 0)
    gross_wpm: Optional[float] = None
    net_wpm: Optional[float] = None
    backspace_ratio: Optional[float] = None
    correction_ratio: Optional[float] = None
    error_correction_efficiency: Optional[float] = None

    if total_keystrokes >= min_keystrokes:
        if blocks.active_typing_s > 0.0:
            active_typing_min = blocks.active_typing_s / 60.0
            gross_wpm = (char_keystrokes / 5.0) / active_typing_min
            net_wpm = max(0.0, char_keystrokes - total_correction_keys) / 5.0 / active_typing_min

        backspace_ratio = backspace_count / total_keystrokes
        correction_ratio = total_correction_keys / total_keystrokes

        if char_keystrokes > 0:
            error_correction_efficiency = max(0.0, char_keystrokes - total_correction_keys) / char_keystrokes

    # 5. Corrections and pauses
    pause_before_correction_ms: Optional[float] = None
    if blocks.n_correction_runs > 0:
        pause_before_correction_ms = blocks.sum_pause_before_correction_ms / blocks.n_correction_runs

    # 6. Bursts
    n_bursts = blocks.n_bursts
    n_long_silences_after_burst = blocks.n_long_silences_after_burst

    mean_burst_len: Optional[float] = None
    burst_to_silence_ratio: Optional[float] = None
    if n_bursts > 0:
        mean_burst_len = blocks.sum_burst_len / n_bursts
        burst_to_silence_ratio = n_bursts / max(1, n_long_silences_after_burst)

    # 7. Key dwell time (optional, reported only if capability available and n > 0)
    mean_dwell_time_ms: Optional[float] = None
    dwell_time_std_ms: Optional[float] = None
    if key_dwell_capable and blocks.dwell_n > 0:
        dn = blocks.dwell_n
        ds = blocks.dwell_sum_ms
        dss = blocks.dwell_sum_sq_ms
        mean_dwell_time_ms = ds / dn
        if dn >= 2:
            d_var = (dss - (ds * ds) / dn) / (dn - 1)
            dwell_time_std_ms = math.sqrt(max(0.0, d_var))

    return {
        "total_keystrokes": total_keystrokes,
        "char_keystrokes": char_keystrokes,
        "backspace_count": backspace_count,
        "delete_count": delete_count,
        "total_correction_keys": total_correction_keys,
        "repeated_backspace_bursts": repeated_backspace_bursts,
        "mean_flight_time_ms": mean_flight_time_ms,
        "flight_time_std_ms": flight_time_std_ms,
        "active_typing_ratio": active_typing_ratio,
        "gross_wpm": gross_wpm,
        "net_wpm": net_wpm,
        "backspace_ratio": backspace_ratio,
        "correction_ratio": correction_ratio,
        "error_correction_efficiency": error_correction_efficiency,
        "pause_before_correction_ms": pause_before_correction_ms,
        "n_bursts": n_bursts,
        "mean_burst_len": mean_burst_len,
        "n_long_silences_after_burst": n_long_silences_after_burst,
        "burst_to_silence_ratio": burst_to_silence_ratio,
        "keystrokes_per_second": keystrokes_per_second,
        "keystroke_coefficient_of_variation": keystroke_coefficient_of_variation,
        "mean_dwell_time_ms": mean_dwell_time_ms,
        "dwell_time_std_ms": dwell_time_std_ms,
    }
