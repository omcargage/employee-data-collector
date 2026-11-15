"""Metrics subpackage containing pure computation functions over window event data.

Computes 15-minute and daily rollups (flight times, error bursts, session metrics) per docs/metrics_spec.md.
"""
from .keyboard_metrics import compute_keyboard_metrics
from .mouse_metrics import compute_mouse_metrics


def compute_rollup_15min_metrics(blocks, *, covered_s=None, **kwargs):
    """Compute combined 15-minute keyboard and mouse metrics from WindowBlocks."""
    kb_metrics = compute_keyboard_metrics(blocks, covered_s=covered_s, **{
        k: v for k, v in kwargs.items() if k in ("min_keystrokes", "min_flight_intervals", "key_dwell_capable")
    })
    mouse_metrics = compute_mouse_metrics(blocks, covered_s=covered_s, **{
        k: v for k, v in kwargs.items() if k in ("min_clicks",)
    })
    return {**kb_metrics, **mouse_metrics}


__all__ = [
    "compute_keyboard_metrics",
    "compute_mouse_metrics",
    "compute_rollup_15min_metrics",
]
