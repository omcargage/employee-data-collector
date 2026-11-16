"""Validation script executing scripted activity patterns through the EDC metric pipeline.

Tests and verifies:
1. Fast typing vs. Slow typing (WPM rises, flight time drops).
2. Clean typing vs. Heavy corrections (backspaces & correction ratios increase).
3. Smooth mouse vs. Mouse jitter (distance, speed, and acceleration increase).

Usage:
    python scripts/validate_activity_patterns.py
"""
import sys

from edc_agent.validation import (
    evaluate_heavy_corrections,
    evaluate_mouse_jitter,
    evaluate_typing_speed,
    run_all_validation_checks,
)


def main() -> int:
    sys.stdout.write("======================================================================\n")
    sys.stdout.write("  EDC Activity Patterns Metric Pipeline Validation\n")
    sys.stdout.write("======================================================================\n\n")

    results = run_all_validation_checks()

    # 1. Typing Speed Test
    res_speed = results["typing_speed"]
    sys.stdout.write("[TEST 1/3] Typing Speed Pattern (Fast vs. Slow)\n")
    sys.stdout.write(f"  Fast Typing: Target={res_speed['fast']['target_wpm']:.1f} WPM | "
                     f"Measured={res_speed['fast']['measured_wpm']:.1f} WPM | "
                     f"Flight Time={res_speed['fast']['mean_flight_time_ms']:.1f} ms\n")
    sys.stdout.write(f"  Slow Typing: Target={res_speed['slow']['target_wpm']:.1f} WPM | "
                     f"Measured={res_speed['slow']['measured_wpm']:.1f} WPM | "
                     f"Flight Time={res_speed['slow']['mean_flight_time_ms']:.1f} ms\n")
    sys.stdout.write(f"  Delta: +{res_speed['wpm_difference']:.1f} WPM (Flight time ratio: {res_speed['flight_ratio']:.2f}x)\n")
    if res_speed["passed"]:
        sys.stdout.write("  --> STATUS: PASSED (WPM increased and flight time decreased as expected)\n\n")
    else:
        sys.stderr.write("  --> STATUS: FAILED\n\n")

    # 2. Heavy Corrections Test
    res_corr = results["heavy_corrections"]
    sys.stdout.write("[TEST 2/3] Correction Pattern (Clean vs. Heavy Corrections)\n")
    sys.stdout.write(f"  Clean Typing: Total Corrections={res_corr['clean']['total_correction_keys']} | "
                     f"Backspaces={res_corr['clean']['backspace_count']} | "
                     f"Correction Ratio={res_corr['clean']['correction_ratio']:.3f}\n")
    sys.stdout.write(f"  Heavy Typing: Total Corrections={res_corr['heavy']['total_correction_keys']} | "
                     f"Backspaces={res_corr['heavy']['backspace_count']} | "
                     f"Correction Ratio={res_corr['heavy']['correction_ratio']:.3f}\n")
    sys.stdout.write(f"  Delta: +{res_corr['corrections_increase']} corrections | +{res_corr['ratio_increase']:.3f} ratio\n")
    if res_corr["passed"]:
        sys.stdout.write("  --> STATUS: PASSED (Corrections, backspaces, and correction ratio increased)\n\n")
    else:
        sys.stderr.write("  --> STATUS: FAILED\n\n")

    # 3. Mouse Jitter Test
    res_jitter = results["mouse_jitter"]
    sys.stdout.write("[TEST 3/3] Mouse Dynamics Pattern (Smooth vs. Jitter)\n")
    sys.stdout.write(f"  Smooth Tracking: Distance={res_jitter['smooth']['mouse_distance_px']:.1f} px | "
                     f"Speed={res_jitter['smooth']['average_speed_px_s']:.1f} px/s | "
                     f"Accel={res_jitter['smooth']['average_abs_accel_px_s2']:.1f} px/s²\n")
    sys.stdout.write(f"  Mouse Jitter:    Distance={res_jitter['jitter']['mouse_distance_px']:.1f} px | "
                     f"Speed={res_jitter['jitter']['average_speed_px_s']:.1f} px/s | "
                     f"Accel={res_jitter['jitter']['average_abs_accel_px_s2']:.1f} px/s²\n")
    sys.stdout.write(f"  Speed Ratio: {res_jitter['speed_ratio']:.2f}x | Distance Ratio: {res_jitter['distance_ratio']:.2f}x\n")
    if res_jitter["passed"]:
        sys.stdout.write("  --> STATUS: PASSED (Distance, speed, and acceleration increased as expected)\n\n")
    else:
        sys.stderr.write("  --> STATUS: FAILED\n\n")

    sys.stdout.write("======================================================================\n")
    if results["all_passed"]:
        sys.stdout.write("  ALL SCRIPTED ACTIVITY PATTERN VALIDATIONS PASSED!\n")
        sys.stdout.write("======================================================================\n")
        return 0
    else:
        sys.stderr.write("  VALIDATION FAILED ON ONE OR MORE PATTERNS\n")
        sys.stdout.write("======================================================================\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
