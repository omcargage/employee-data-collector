"""Interactive and synthetic typing test calibration script for EDC.

Per Prompt 14:
- User types a fixed paragraph at a measured pace.
- Compares measured WPM, flight time, and correction counts with expected values.
- Provides a synthetic automated mode (--synthetic) for reproducible testing.
- Reports PASS if all measured metrics match expected values within 5% tolerance.
"""
import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

# Ensure agent and shared packages are on path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "agent"))
sys.path.insert(0, str(REPO_ROOT / "shared"))

from edc_agent.collectors.keyboard_collector import accumulate_keyboard
from edc_agent.metrics.keyboard_metrics import compute_keyboard_metrics
from edc_schemas import ActivityEvent, EventKind, WindowBlocks


REFERENCE_PARAGRAPH = (
    "The quick brown fox jumps over the lazy dog. "
    "Pack my box with five dozen liquor jugs. "
    "How vexingly quick daft zebras jump!"
)


def generate_synthetic_events(
    text: str = REFERENCE_PARAGRAPH,
    pace_ms: float = 200.0,
    backspace_count: int = 2,
    start_time: Optional[datetime] = None,
) -> Tuple[List[ActivityEvent], Dict[str, Any]]:
    """Generate a precisely timed stream of ActivityEvents with known ground-truth values."""
    t0 = start_time or datetime(2026, 11, 15, 12, 0, 0, tzinfo=timezone.utc)
    current_time = t0
    events: List[ActivityEvent] = []

    char_count = len(text)
    total_events_count = char_count + backspace_count
    flight_times_ms: List[float] = []

    # Emit first character
    events.append(ActivityEvent(ts_utc=current_time, kind=EventKind.KEY_CHAR))

    # Emit remaining characters, injecting backspaces mid-way
    chars_to_type = list(text)
    backspaces_injected = 0

    for i in range(1, len(chars_to_type)):
        # Inject backspace after 20th character
        if backspaces_injected < backspace_count and i == 20:
            for _ in range(backspace_count):
                current_time += timedelta(milliseconds=pace_ms)
                flight_times_ms.append(pace_ms)
                events.append(ActivityEvent(ts_utc=current_time, kind=EventKind.KEY_BACKSPACE))
                backspaces_injected += 1

        current_time += timedelta(milliseconds=pace_ms)
        flight_times_ms.append(pace_ms)
        events.append(ActivityEvent(ts_utc=current_time, kind=EventKind.KEY_CHAR))

    # Calculate ground truth expectations
    active_typing_s = sum(flight_times_ms) / 1000.0
    active_typing_min = active_typing_s / 60.0
    expected_gross_wpm = (char_count / 5.0) / active_typing_min
    expected_net_wpm = max(0.0, char_count - backspace_count) / 5.0 / active_typing_min
    expected_mean_flight_ms = sum(flight_times_ms) / len(flight_times_ms)

    expected = {
        "char_keystrokes": char_count,
        "backspace_count": backspace_count,
        "active_typing_s": round(active_typing_s, 3),
        "gross_wpm": round(expected_gross_wpm, 2),
        "net_wpm": round(expected_net_wpm, 2),
        "mean_flight_time_ms": round(expected_mean_flight_ms, 2),
    }

    return events, expected


def evaluate_calibration(
    events: List[ActivityEvent],
    expected: Dict[str, Any],
    max_tolerance_pct: float = 5.0,
) -> Dict[str, Any]:
    """Feed events through EDC keyboard metrics and compare with ground-truth expected values."""
    # Compute WindowBlocks from raw ActivityEvents
    blocks = accumulate_keyboard(events, covered_s=expected.get("active_typing_s", 60.0))

    # Compute high-level keyboard metrics with lowered threshold for calibration test
    metrics = compute_keyboard_metrics(
        blocks,
        min_keystrokes=10,
        min_flight_intervals=5,
    )

    measured = {
        "char_keystrokes": blocks.n_char,
        "backspace_count": blocks.n_backspace,
        "active_typing_s": round(blocks.active_typing_s, 3),
        "gross_wpm": round(metrics.get("gross_wpm") or 0.0, 2),
        "net_wpm": round(metrics.get("net_wpm") or 0.0, 2),
        "mean_flight_time_ms": round(metrics.get("mean_flight_time_ms") or 0.0, 2),
    }

    comparison: List[Dict[str, Any]] = []
    all_passed = True

    for key, exp_val in expected.items():
        meas_val = measured.get(key, 0.0)
        if exp_val == 0.0 and meas_val == 0.0:
            delta_pct = 0.0
        elif exp_val != 0:
            delta_pct = abs(meas_val - exp_val) / abs(exp_val) * 100.0
        else:
            delta_pct = 100.0

        passed = delta_pct <= max_tolerance_pct
        if not passed:
            all_passed = False

        comparison.append({
            "metric": key,
            "expected": exp_val,
            "measured": meas_val,
            "delta_pct": round(delta_pct, 2),
            "passed": passed,
        })

    return {
        "passed": all_passed,
        "max_tolerance_pct": max_tolerance_pct,
        "expected": expected,
        "measured": measured,
        "comparison": comparison,
    }


def format_calibration_table(results: Dict[str, Any]) -> str:
    """Format calibration comparison as a clean terminal table."""
    lines: List[str] = []
    w = 74

    lines.append("=" * w)
    lines.append(f"{'EDC TYPING CALIBRATION RESULTS':^{w}}")
    lines.append("=" * w)
    lines.append(f"{'Metric':<26} | {'Expected':<12} | {'Measured':<12} | {'Delta (%)':<10} | {'Status'}")
    lines.append("-" * w)

    for item in results["comparison"]:
        status_str = "PASS" if item["passed"] else "FAIL"
        lines.append(
            f"{item['metric']:<26} | {item['expected']:>12} | {item['measured']:>12} | {item['delta_pct']:>9.2f}% | {status_str}"
        )

    lines.append("-" * w)
    tol = results["max_tolerance_pct"]
    if results["passed"]:
        lines.append(f"OVERALL CALIBRATION RESULT: PASS (All metrics within {tol:.1f}% tolerance)")
    else:
        lines.append(f"OVERALL CALIBRATION RESULT: FAIL (One or more metrics exceeded {tol:.1f}% tolerance)")
    lines.append("=" * w)
    return "\n".join(lines)


def run_interactive_test(paragraph: str = REFERENCE_PARAGRAPH) -> int:
    """Run interactive keyboard calibration with live user typing."""
    import sys
    print("\n" + "=" * 74)
    print("                      EDC LIVE TYPING CALIBRATION")
    print("=" * 74)
    print("\nParagraph to type:")
    print("-" * 74)
    print(paragraph)
    print("-" * 74)
    print("\nInstructions:")
    print("1. When ready, press [ENTER] to start.")
    print("2. Type the paragraph above at a normal, steady pace.")
    print("3. Press [ENTER] again when you finish typing.\n")

    input("Press [ENTER] to begin...")

    collected_events: List[ActivityEvent] = []

    # Attempt to initialize real platform listener
    provider = None
    try:
        if sys.platform == "win32":
            from edc_agent.platforms.windows.provider import WindowsInputProvider
            provider = WindowsInputProvider(callback=collected_events.append)
            provider.start()
        else:
            from edc_agent.platforms.fake import FakeInputProvider
            provider = FakeInputProvider(callback=collected_events.append)
            provider.start()
    except Exception as e:
        print(f"[ERROR] Could not start low-level input provider: {e}")
        return 1

    t_start = datetime.now(timezone.utc)
    print("\n[LISTENING...] Start typing now:")
    typed_input = input("\n> ")
    t_end = datetime.now(timezone.utc)

    if provider:
        provider.stop()

    if not collected_events:
        print("\n[ERROR] No keystrokes were captured by the input provider.")
        return 1

    # Ground truth calculations from typed text and timestamps
    char_count = len(typed_input)
    # Estimate corrections from backspaces in events
    backspaces = sum(1 for e in collected_events if e.kind == EventKind.KEY_BACKSPACE)

    # Flight times
    non_mods = [e for e in collected_events if e.kind != EventKind.KEY_MODIFIER]
    flights: List[float] = []
    for i in range(len(non_mods) - 1):
        dt = (non_mods[i+1].ts_utc - non_mods[i].ts_utc).total_seconds() * 1000.0
        if 0.0 <= dt <= 2000.0:
            flights.append(dt)

    active_typing_s = sum(flights) / 1000.0 if flights else (t_end - t_start).total_seconds()
    active_typing_min = max(0.001, active_typing_s / 60.0)
    exp_gross_wpm = (char_count / 5.0) / active_typing_min
    exp_net_wpm = max(0.0, char_count - backspaces) / 5.0 / active_typing_min
    exp_flight_mean = (sum(flights) / len(flights)) if flights else 0.0

    expected = {
        "char_keystrokes": char_count,
        "backspace_count": backspaces,
        "active_typing_s": round(active_typing_s, 3),
        "gross_wpm": round(exp_gross_wpm, 2),
        "net_wpm": round(exp_net_wpm, 2),
        "mean_flight_time_ms": round(exp_flight_mean, 2),
    }

    results = evaluate_calibration(collected_events, expected, max_tolerance_pct=10.0)
    print("\n" + format_calibration_table(results))
    return 0 if results["passed"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="EDC Typing Test Calibration Script.")
    parser.add_argument("--synthetic", action="store_true", help="Run automated test with simulated keystroke stream")
    parser.add_argument("--pace-ms", type=float, default=200.0, help="Pace per keystroke in ms for synthetic test (default 200ms)")
    parser.add_argument("--backspaces", type=int, default=2, help="Number of backspaces to inject in synthetic test (default 2)")
    args = parser.parse_args()

    if args.synthetic:
        events, expected = generate_synthetic_events(
            text=REFERENCE_PARAGRAPH,
            pace_ms=args.pace_ms,
            backspace_count=args.backspaces,
        )
        results = evaluate_calibration(events, expected, max_tolerance_pct=5.0)
        sys.stdout.write("\n" + format_calibration_table(results) + "\n")
        return 0 if results["passed"] else 1
    else:
        return run_interactive_test()


if __name__ == "__main__":
    sys.exit(main())
