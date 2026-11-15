"""Pure functions computing 15-minute mouse metrics from WindowBlocks per Spec Section 5.

Applies authoritative null rules:
- min_clicks: returns None if click_interval_n < min_clicks (default 5) for click intervals mean/std/CV.
- n_moving_bins == 0: returns None for average_speed_px_s.
- n_accel_samples == 0: returns None for average_abs_accel_px_s2.
"""
import math
from typing import Any, Dict, Optional

from edc_schemas import WindowBlocks


def compute_mouse_metrics(
    blocks: WindowBlocks,
    *,
    covered_s: Optional[float] = None,
    min_clicks: int = 5,
) -> Dict[str, Any]:
    """Compute 15-minute mouse metrics from WindowBlocks building blocks.

    Pure function over plain data. Missing statistics return None, never 0.
    """
    effective_covered_s = covered_s if covered_s is not None else blocks.covered_s

    # 1. Clicks and click rate
    click_count = blocks.n_clicks
    clicks_per_second: Optional[float] = None
    if effective_covered_s > 0.0:
        clicks_per_second = click_count / effective_covered_s

    # 2. Click intervals (null rule: click_interval_n < min_clicks)
    average_interval_seconds: Optional[float] = None
    click_interval_stdev_seconds: Optional[float] = None
    coefficient_of_variation: Optional[float] = None

    if blocks.click_interval_n >= min_clicks:
        cn = blocks.click_interval_n
        cs = blocks.click_interval_sum_s
        css = blocks.click_interval_sum_sq_s

        average_interval_seconds = cs / cn
        if cn >= 2:
            c_var = (css - (cs * cs) / cn) / (cn - 1)
            click_interval_stdev_seconds = math.sqrt(max(0.0, c_var))
            if average_interval_seconds > 0.0:
                coefficient_of_variation = click_interval_stdev_seconds / average_interval_seconds

    # 3. Pointer speed and acceleration
    average_speed_px_s: Optional[float] = None
    if blocks.n_moving_bins > 0:
        average_speed_px_s = blocks.sum_speed_px_s / blocks.n_moving_bins

    average_abs_accel_px_s2: Optional[float] = None
    if blocks.n_accel_samples > 0:
        average_abs_accel_px_s2 = blocks.sum_abs_accel_px_s2 / blocks.n_accel_samples

    # 4. Scroll metrics
    total_abs_scroll_ticks = blocks.n_scroll_ticks_abs
    average_abs_scroll_ticks_s: Optional[float] = None
    if effective_covered_s > 0.0:
        average_abs_scroll_ticks_s = total_abs_scroll_ticks / effective_covered_s

    double_click_count = blocks.n_double_clicks
    rapid_click_runs = blocks.n_rapid_click_runs
    scroll_reversal_count = blocks.n_scroll_reversals

    # 5. Idle times
    pointer_idle_s: Optional[float] = None
    if effective_covered_s > 0.0:
        pointer_idle_s = blocks.idle_s

    short_idle_total_s = blocks.idle_s

    return {
        "click_count": click_count,
        "clicks_per_second": clicks_per_second,
        "average_interval_seconds": average_interval_seconds,
        "click_interval_stdev_seconds": click_interval_stdev_seconds,
        "coefficient_of_variation": coefficient_of_variation,
        "average_speed_px_s": average_speed_px_s,
        "average_abs_accel_px_s2": average_abs_accel_px_s2,
        "total_abs_scroll_ticks": total_abs_scroll_ticks,
        "average_abs_scroll_ticks_s": average_abs_scroll_ticks_s,
        "double_click_count": double_click_count,
        "rapid_click_runs": rapid_click_runs,
        "scroll_reversal_count": scroll_reversal_count,
        "pointer_idle_s": pointer_idle_s,
        "short_idle_total_s": short_idle_total_s,
    }
