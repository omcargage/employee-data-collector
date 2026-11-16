"""Validation subpackage for testing behavioral patterns against EDC metric algorithms."""
from .evaluator import (
    evaluate_heavy_corrections,
    evaluate_mouse_jitter,
    evaluate_typing_speed,
    run_all_validation_checks,
)
from .patterns import (
    generate_heavy_correction_stream,
    generate_mouse_jitter_stream,
    generate_smooth_mouse_stream,
    generate_typing_stream,
)

__all__ = [
    "generate_typing_stream",
    "generate_heavy_correction_stream",
    "generate_mouse_jitter_stream",
    "generate_smooth_mouse_stream",
    "evaluate_typing_speed",
    "evaluate_heavy_corrections",
    "evaluate_mouse_jitter",
    "run_all_validation_checks",
]
