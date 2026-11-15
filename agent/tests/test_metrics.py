"""Unit tests for keyboard and mouse metrics calculations per Spec Sections 4 and 5.

Validates:
1. Known typing scenario (e.g. 300 chars in scripted 60 s with known corrections -> exact gross/net WPM).
2. CV and sample standard deviation from sum and sum_sq match numpy (ddof=1) exactly.
3. Below-threshold windows return None (null), never 0 or 0.0.
4. Merging two windows' blocks gives identical stats to computing on the combined window.
"""
import math
import numpy as np
import pytest

from edc_schemas import WindowBlocks
from edc_agent.metrics import (
    compute_keyboard_metrics,
    compute_mouse_metrics,
    compute_rollup_15min_metrics,
)


def test_known_typing_scenario_wpm_and_ratios():
    """Verify known typing scenario matches exact hand-computed gross/net WPM and ratios.

    === Arithmetic Verification ===
    char_keystrokes = 300
    backspace_count = 15
    delete_count = 5
    total_correction_keys = 15 + 5 = 20
    total_keystrokes = 300 + 15 + 5 = 320 (>= min_keystrokes = 30)
    active_typing_s = 60.0 s (= 1.0 min)
    covered_s = 900.0 s (= 15.0 min)

    gross_wpm = (char_keystrokes / 5) / (active_typing_s / 60)
              = (300 / 5) / (60.0 / 60.0) = 60 / 1.0 = 60.0 WPM
    net_wpm   = max(0, char_keystrokes - total_correction_keys) / 5 / (active_typing_s / 60)
              = max(0, 300 - 20) / 5 / 1.0 = 280 / 5 / 1.0 = 56.0 WPM
    backspace_ratio = 15 / 320 = 0.046875
    correction_ratio = 20 / 320 = 0.0625
    error_correction_efficiency = (300 - 20) / 300 = 280 / 300 = 14 / 15 ≈ 0.9333333333
    active_typing_ratio = 60.0 / 900.0 = 1 / 15 ≈ 0.0666666667
    keystrokes_per_second = 320 / 900.0 ≈ 0.3555555556
    """
    blocks = WindowBlocks(
        n_char=300,
        n_backspace=15,
        n_delete=5,
        n_other_key=0,
        active_typing_s=60.0,
        covered_s=900.0,
    )

    metrics = compute_keyboard_metrics(blocks, min_keystrokes=30)

    assert metrics["total_keystrokes"] == 320
    assert metrics["char_keystrokes"] == 300
    assert metrics["backspace_count"] == 15
    assert metrics["delete_count"] == 5
    assert metrics["total_correction_keys"] == 20

    assert metrics["gross_wpm"] == pytest.approx(60.0)
    assert metrics["net_wpm"] == pytest.approx(56.0)
    assert metrics["backspace_ratio"] == pytest.approx(15 / 320)
    assert metrics["correction_ratio"] == pytest.approx(20 / 320)
    assert metrics["error_correction_efficiency"] == pytest.approx(280 / 300)
    assert metrics["active_typing_ratio"] == pytest.approx(60.0 / 900.0)
    assert metrics["keystrokes_per_second"] == pytest.approx(320 / 900.0)


def test_cv_and_std_from_sums_match_numpy():
    """Verify that sample standard deviation and CV computed from sum & sum_sq match numpy (ddof=1)."""
    # 1. Keyboard flight times
    raw_flights = [115.0, 145.0, 210.0, 290.0, 340.0, 480.0, 520.0, 710.0, 890.0, 1200.0, 1650.0]
    n_f = len(raw_flights)
    sum_f = sum(raw_flights)
    sum_sq_f = sum(x * x for x in raw_flights)

    np_mean_f = float(np.mean(raw_flights))
    np_std_f = float(np.std(raw_flights, ddof=1))
    np_cv_f = np_std_f / np_mean_f

    kb_blocks = WindowBlocks(
        flight_time_n=n_f,
        flight_time_sum_ms=sum_f,
        flight_time_sum_sq_ms=sum_sq_f,
    )
    kb_metrics = compute_keyboard_metrics(kb_blocks, min_flight_intervals=10)

    assert kb_metrics["mean_flight_time_ms"] == pytest.approx(np_mean_f, rel=1e-7)
    assert kb_metrics["flight_time_std_ms"] == pytest.approx(np_std_f, rel=1e-7)
    assert kb_metrics["keystroke_coefficient_of_variation"] == pytest.approx(np_cv_f, rel=1e-7)

    # 2. Mouse click intervals
    raw_clicks = [0.85, 1.20, 1.95, 2.40, 3.10, 4.05]
    n_c = len(raw_clicks)
    sum_c = sum(raw_clicks)
    sum_sq_c = sum(c * c for c in raw_clicks)

    np_mean_c = float(np.mean(raw_clicks))
    np_std_c = float(np.std(raw_clicks, ddof=1))
    np_cv_c = np_std_c / np_mean_c

    mouse_blocks = WindowBlocks(
        n_clicks=n_c + 1,
        click_interval_n=n_c,
        click_interval_sum_s=sum_c,
        click_interval_sum_sq_s=sum_sq_c,
    )
    mouse_metrics = compute_mouse_metrics(mouse_blocks, min_clicks=5)

    assert mouse_metrics["average_interval_seconds"] == pytest.approx(np_mean_c, rel=1e-7)
    assert mouse_metrics["click_interval_stdev_seconds"] == pytest.approx(np_std_c, rel=1e-7)
    assert mouse_metrics["coefficient_of_variation"] == pytest.approx(np_cv_c, rel=1e-7)


def test_below_threshold_windows_return_none_not_zero():
    """Verify that whenever observations are below threshold, metrics return None (null), never 0."""
    # 1. Keyboard: total_keystrokes < min_keystrokes (e.g. 25 < 30)
    # flight_time_n < min_flight_intervals (e.g. 8 < 10)
    sparse_kb = WindowBlocks(
        n_char=20,
        n_backspace=5,
        active_typing_s=15.0,
        flight_time_n=8,
        flight_time_sum_ms=1600.0,
        flight_time_sum_sq_ms=350000.0,
        covered_s=900.0,
    )
    kb_res = compute_keyboard_metrics(sparse_kb, min_keystrokes=30, min_flight_intervals=10)

    # WPM and ratios MUST be None, not 0 or 0.0
    assert kb_res["gross_wpm"] is None
    assert kb_res["net_wpm"] is None
    assert kb_res["backspace_ratio"] is None
    assert kb_res["correction_ratio"] is None
    assert kb_res["error_correction_efficiency"] is None

    # Flight time stats MUST be None, not 0 or 0.0
    assert kb_res["mean_flight_time_ms"] is None
    assert kb_res["flight_time_std_ms"] is None
    assert kb_res["keystroke_coefficient_of_variation"] is None

    # But counts remain valid non-null integers
    assert kb_res["total_keystrokes"] == 25
    assert kb_res["char_keystrokes"] == 20
    assert kb_res["backspace_count"] == 5

    # 2. Mouse: click_interval_n < min_clicks (e.g. 3 < 5)
    sparse_mouse = WindowBlocks(
        n_clicks=4,
        click_interval_n=3,
        click_interval_sum_s=4.5,
        click_interval_sum_sq_s=7.2,
        n_moving_bins=0,
        sum_speed_px_s=0.0,
        n_accel_samples=0,
        sum_abs_accel_px_s2=0.0,
        covered_s=900.0,
    )
    mouse_res = compute_mouse_metrics(sparse_mouse, min_clicks=5)

    # Click interval stats MUST be None, not 0
    assert mouse_res["average_interval_seconds"] is None
    assert mouse_res["click_interval_stdev_seconds"] is None
    assert mouse_res["coefficient_of_variation"] is None

    # Speed and acceleration MUST be None when n_bins == 0
    assert mouse_res["average_speed_px_s"] is None
    assert mouse_res["average_abs_accel_px_s2"] is None

    # Counts remain valid integers
    assert mouse_res["click_count"] == 4


def test_merging_two_windows_blocks_matches_combined_calculation():
    """Verify that merging two WindowBlocks gives identical statistics to a single combined window."""
    # Window 1 raw values
    w1_flights = [120.0, 150.0, 200.0, 250.0, 300.0, 400.0, 600.0, 800.0, 1000.0, 1200.0]
    w1_clicks = [0.8, 1.2, 1.5, 2.0, 2.5, 3.0]
    block1 = WindowBlocks(
        n_char=50,
        n_backspace=5,
        n_delete=1,
        n_other_key=4,
        n_clicks=7,
        n_double_clicks=1,
        n_rapid_click_runs=1,
        n_scroll_ticks_abs=12,
        n_scroll_reversals=1,
        flight_time_n=len(w1_flights),
        flight_time_sum_ms=sum(w1_flights),
        flight_time_sum_sq_ms=sum(x * x for x in w1_flights),
        click_interval_n=len(w1_clicks),
        click_interval_sum_s=sum(w1_clicks),
        click_interval_sum_sq_s=sum(c * c for c in w1_clicks),
        n_moving_bins=5,
        sum_speed_px_s=1200.0,
        n_accel_samples=4,
        sum_abs_accel_px_s2=4000.0,
        active_typing_s=sum(w1_flights) / 1000.0,
        covered_s=900.0,
        idle_s=120.0,
        n_bursts=2,
        sum_burst_len=14,
        n_long_silences_after_burst=1,
        n_correction_runs=2,
        n_backspace_bursts=1,
        sum_pause_before_correction_ms=750.0,
    )

    # Window 2 raw values
    w2_flights = [100.0, 180.0, 220.0, 310.0, 450.0, 550.0, 750.0, 950.0, 1100.0, 1300.0, 1500.0]
    w2_clicks = [0.5, 1.0, 1.8, 2.2, 2.8, 3.5]
    block2 = WindowBlocks(
        n_char=60,
        n_backspace=8,
        n_delete=2,
        n_other_key=6,
        n_clicks=8,
        n_double_clicks=2,
        n_rapid_click_runs=0,
        n_scroll_ticks_abs=18,
        n_scroll_reversals=2,
        flight_time_n=len(w2_flights),
        flight_time_sum_ms=sum(w2_flights),
        flight_time_sum_sq_ms=sum(x * x for x in w2_flights),
        click_interval_n=len(w2_clicks),
        click_interval_sum_s=sum(w2_clicks),
        click_interval_sum_sq_s=sum(c * c for c in w2_clicks),
        n_moving_bins=6,
        sum_speed_px_s=1800.0,
        n_accel_samples=5,
        sum_abs_accel_px_s2=5500.0,
        active_typing_s=sum(w2_flights) / 1000.0,
        covered_s=900.0,
        idle_s=180.0,
        n_bursts=3,
        sum_burst_len=20,
        n_long_silences_after_burst=2,
        n_correction_runs=3,
        n_backspace_bursts=2,
        sum_pause_before_correction_ms=1100.0,
    )

    # Merged block
    merged_block = block1 + block2

    # Combined block directly from raw pooled data
    pooled_flights = w1_flights + w2_flights
    pooled_clicks = w1_clicks + w2_clicks
    combined_direct_block = WindowBlocks(
        n_char=50 + 60,
        n_backspace=5 + 8,
        n_delete=1 + 2,
        n_other_key=4 + 6,
        n_clicks=7 + 8,
        n_double_clicks=1 + 2,
        n_rapid_click_runs=1 + 0,
        n_scroll_ticks_abs=12 + 18,
        n_scroll_reversals=1 + 2,
        flight_time_n=len(pooled_flights),
        flight_time_sum_ms=sum(pooled_flights),
        flight_time_sum_sq_ms=sum(x * x for x in pooled_flights),
        click_interval_n=len(pooled_clicks),
        click_interval_sum_s=sum(pooled_clicks),
        click_interval_sum_sq_s=sum(c * c for c in pooled_clicks),
        n_moving_bins=5 + 6,
        sum_speed_px_s=1200.0 + 1800.0,
        n_accel_samples=4 + 5,
        sum_abs_accel_px_s2=4000.0 + 5500.0,
        active_typing_s=(sum(w1_flights) + sum(w2_flights)) / 1000.0,
        covered_s=900.0 + 900.0,
        idle_s=120.0 + 180.0,
        n_bursts=2 + 3,
        sum_burst_len=14 + 20,
        n_long_silences_after_burst=1 + 2,
        n_correction_runs=2 + 3,
        n_backspace_bursts=1 + 2,
        sum_pause_before_correction_ms=750.0 + 1100.0,
    )

    # Compute rollup metrics on both
    merged_metrics = compute_rollup_15min_metrics(merged_block)
    direct_metrics = compute_rollup_15min_metrics(combined_direct_block)

    # Verify every metric matches exactly
    for key in merged_metrics:
        val_m = merged_metrics[key]
        val_d = direct_metrics[key]
        if val_m is None:
            assert val_d is None, f"Mismatch for {key}: {val_m} vs {val_d}"
        else:
            assert val_m == pytest.approx(val_d), f"Mismatch for {key}: {val_m} vs {val_d}"
