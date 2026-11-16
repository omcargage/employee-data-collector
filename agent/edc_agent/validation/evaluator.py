"""Evaluates scripted activity patterns through the EDC metric pipeline.

Asserts that:
1. Fast typing produces significantly higher gross/net WPM and lower flight times than slow typing.
2. Heavy correction typing produces significantly higher correction keys, backspaces, and correction ratios than clean typing.
3. Mouse jitter produces significantly higher mouse distance, average speed, and acceleration than smooth mouse tracking.
"""
from typing import Any, Dict

from edc_agent.collectors import accumulate_window_blocks
from edc_agent.metrics import compute_rollup_15min_metrics
from edc_agent.validation.patterns import (
    generate_heavy_correction_stream,
    generate_mouse_jitter_stream,
    generate_smooth_mouse_stream,
    generate_typing_stream,
)


def evaluate_typing_speed(
    fast_wpm: float = 90.0,
    slow_wpm: float = 25.0,
    n_keystrokes: int = 200,
) -> Dict[str, Any]:
    """Verify that fast typing produces higher WPM and lower flight time than slow typing."""
    fast_events = generate_typing_stream(target_wpm=fast_wpm, n_keystrokes=n_keystrokes, seed=42)
    slow_events = generate_typing_stream(target_wpm=slow_wpm, n_keystrokes=n_keystrokes, seed=43)

    fast_duration = (fast_events[-1].ts_utc - fast_events[0].ts_utc).total_seconds()
    slow_duration = (slow_events[-1].ts_utc - slow_events[0].ts_utc).total_seconds()

    fast_blocks = accumulate_window_blocks(fast_events, covered_s=fast_duration)
    slow_blocks = accumulate_window_blocks(slow_events, covered_s=slow_duration)

    fast_metrics = compute_rollup_15min_metrics(fast_blocks, covered_s=fast_duration)
    slow_metrics = compute_rollup_15min_metrics(slow_blocks, covered_s=slow_duration)

    fast_measured_wpm = fast_metrics.get("gross_wpm") or 0.0
    slow_measured_wpm = slow_metrics.get("gross_wpm") or 0.0
    fast_flight_ms = fast_metrics.get("mean_flight_time_ms") or 0.0
    slow_flight_ms = slow_metrics.get("mean_flight_time_ms") or 0.0

    passed = (fast_measured_wpm > slow_measured_wpm) and (fast_flight_ms < slow_flight_ms)

    return {
        "passed": passed,
        "fast": {
            "target_wpm": fast_wpm,
            "measured_wpm": fast_measured_wpm,
            "mean_flight_time_ms": fast_flight_ms,
        },
        "slow": {
            "target_wpm": slow_wpm,
            "measured_wpm": slow_measured_wpm,
            "mean_flight_time_ms": slow_flight_ms,
        },
        "wpm_difference": fast_measured_wpm - slow_measured_wpm,
        "flight_ratio": slow_flight_ms / max(0.01, fast_flight_ms),
    }


def evaluate_heavy_corrections(n_words: int = 35) -> Dict[str, Any]:
    """Verify that error-prone typing with heavy corrections shifts correction metrics upward."""
    clean_events = generate_typing_stream(target_wpm=55.0, n_keystrokes=n_words * 5, correction_rate=0.01, seed=50)
    heavy_events = generate_heavy_correction_stream(n_words=n_words, seed=51)

    clean_duration = (clean_events[-1].ts_utc - clean_events[0].ts_utc).total_seconds()
    heavy_duration = (heavy_events[-1].ts_utc - heavy_events[0].ts_utc).total_seconds()

    clean_blocks = accumulate_window_blocks(clean_events, covered_s=clean_duration)
    heavy_blocks = accumulate_window_blocks(heavy_events, covered_s=heavy_duration)

    clean_metrics = compute_rollup_15min_metrics(clean_blocks, covered_s=clean_duration)
    heavy_metrics = compute_rollup_15min_metrics(heavy_blocks, covered_s=heavy_duration)

    clean_corrections = clean_metrics.get("total_correction_keys") or 0
    heavy_corrections = heavy_metrics.get("total_correction_keys") or 0

    clean_corr_ratio = clean_metrics.get("correction_ratio") or 0.0
    heavy_corr_ratio = heavy_metrics.get("correction_ratio") or 0.0

    clean_backspaces = clean_metrics.get("backspace_count") or 0
    heavy_backspaces = heavy_metrics.get("backspace_count") or 0

    passed = (
        (heavy_corrections > clean_corrections)
        and (heavy_corr_ratio > clean_corr_ratio)
        and (heavy_backspaces > clean_backspaces)
    )

    return {
        "passed": passed,
        "clean": {
            "total_correction_keys": clean_corrections,
            "backspace_count": clean_backspaces,
            "correction_ratio": clean_corr_ratio,
        },
        "heavy": {
            "total_correction_keys": heavy_corrections,
            "backspace_count": heavy_backspaces,
            "correction_ratio": heavy_corr_ratio,
        },
        "corrections_increase": heavy_corrections - clean_corrections,
        "ratio_increase": heavy_corr_ratio - clean_corr_ratio,
    }


def evaluate_mouse_jitter(duration_s: float = 30.0) -> Dict[str, Any]:
    """Verify that mouse jitter produces higher pointer distance, speed, and acceleration."""
    smooth_events = generate_smooth_mouse_stream(duration_s=duration_s, linear_speed_px_s=40.0)
    jitter_events = generate_mouse_jitter_stream(duration_s=duration_s, jitter_magnitude=250.0, seed=77)

    smooth_blocks = accumulate_window_blocks(smooth_events, covered_s=duration_s)
    jitter_blocks = accumulate_window_blocks(jitter_events, covered_s=duration_s)

    smooth_metrics = compute_rollup_15min_metrics(smooth_blocks, covered_s=duration_s)
    jitter_metrics = compute_rollup_15min_metrics(jitter_blocks, covered_s=duration_s)

    smooth_speed = smooth_metrics.get("average_speed_px_s") or 0.0
    jitter_speed = jitter_metrics.get("average_speed_px_s") or 0.0

    smooth_dist = smooth_blocks.sum_speed_px_s * 0.1
    jitter_dist = jitter_blocks.sum_speed_px_s * 0.1

    smooth_accel = smooth_metrics.get("average_abs_accel_px_s2") or 0.0
    jitter_accel = jitter_metrics.get("average_abs_accel_px_s2") or 0.0

    passed = (jitter_speed > smooth_speed) and (jitter_dist > smooth_dist) and (jitter_accel > smooth_accel)

    return {
        "passed": passed,
        "smooth": {
            "mouse_distance_px": smooth_dist,
            "average_speed_px_s": smooth_speed,
            "average_abs_accel_px_s2": smooth_accel,
        },
        "jitter": {
            "mouse_distance_px": jitter_dist,
            "average_speed_px_s": jitter_speed,
            "average_abs_accel_px_s2": jitter_accel,
        },
        "speed_ratio": jitter_speed / max(0.1, smooth_speed),
        "distance_ratio": jitter_dist / max(0.1, smooth_dist),
    }


def run_all_validation_checks() -> Dict[str, Any]:
    """Execute all three validation checks and return aggregate test results."""
    res_speed = evaluate_typing_speed()
    res_corr = evaluate_heavy_corrections()
    res_jitter = evaluate_mouse_jitter()

    all_passed = res_speed["passed"] and res_corr["passed"] and res_jitter["passed"]

    return {
        "all_passed": all_passed,
        "typing_speed": res_speed,
        "heavy_corrections": res_corr,
        "mouse_jitter": res_jitter,
    }
