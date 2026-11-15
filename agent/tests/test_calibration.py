"""Regression and validation tests for typing test calibration and key classification."""
from datetime import datetime, timezone
from pathlib import Path
import sys
import pytest
from pynput.keyboard import Key, KeyCode

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from edc_agent.platforms.windows.provider import WindowsInputProvider
from edc_schemas import ActivityEvent, EventKind
from scripts.calibration_typing_test import (
    evaluate_calibration,
    generate_synthetic_events,
    REFERENCE_PARAGRAPH,
)


def test_synthetic_typing_calibration_matches_expected():
    """Verify that simulated typing produces measured WPM and flight times matching expected values <= 1%."""
    events, expected = generate_synthetic_events(
        text=REFERENCE_PARAGRAPH,
        pace_ms=200.0,
        backspace_count=3,
    )
    result = evaluate_calibration(events, expected, max_tolerance_pct=1.0)
    assert result["passed"] is True

    for comp in result["comparison"]:
        assert comp["passed"] is True, f"Metric {comp['metric']} exceeded tolerance with delta {comp['delta_pct']}%"
        assert comp["delta_pct"] <= 1.0


def test_pace_variations_calibration():
    """Verify calibration accuracy across different typing paces (40 WPM / 300ms, 80 WPM / 150ms)."""
    # Slow typing: 300ms pace (~40 WPM)
    events_slow, exp_slow = generate_synthetic_events(pace_ms=300.0, backspace_count=1)
    res_slow = evaluate_calibration(events_slow, exp_slow, max_tolerance_pct=1.0)
    assert res_slow["passed"] is True
    assert res_slow["measured"]["gross_wpm"] == pytest.approx(exp_slow["gross_wpm"], rel=0.01)

    # Fast typing: 150ms pace (~80 WPM)
    events_fast, exp_fast = generate_synthetic_events(pace_ms=150.0, backspace_count=4)
    res_fast = evaluate_calibration(events_fast, exp_fast, max_tolerance_pct=1.0)
    assert res_fast["passed"] is True
    assert res_fast["measured"]["gross_wpm"] == pytest.approx(exp_fast["gross_wpm"], rel=0.01)


def test_spacebar_classification_bug_regression():
    """Regression test: Key.space must classify as KEY_CHAR so spaces participate in char_keystrokes and WPM.

    Previously, Key.space lacked a .char attribute in pynput and fell back to KEY_OTHER,
    which caused ~20% undercounting of words and WPM in natural typing.
    """
    provider = WindowsInputProvider(callback=lambda e: None)

    # Key.space must classify as EventKind.KEY_CHAR
    kind_space = provider._classify_key(Key.space)
    assert kind_space == EventKind.KEY_CHAR, f"Key.space must be KEY_CHAR, got {kind_space}"

    # Printable character must also be KEY_CHAR
    kind_a = provider._classify_key(KeyCode.from_char("a"))
    assert kind_a == EventKind.KEY_CHAR

    # Backspace must be KEY_BACKSPACE
    kind_bs = provider._classify_key(Key.backspace)
    assert kind_bs == EventKind.KEY_BACKSPACE
