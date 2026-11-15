"""Unit and integration tests for scripts/data_quality_report.py."""
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import sys
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from edc_agent.storage.database import Database
from edc_schemas import Rollup15Min, RollupDaily, WindowBlocks
from scripts.data_quality_report import (
    compute_metric_stats,
    find_impossible_values,
    format_report_text,
    generate_data_quality_report,
)


def test_compute_metric_stats_empty_and_valid():
    """Verify statistical computations for empty, mixed null, and numeric arrays."""
    # Empty list
    st_empty = compute_metric_stats([])
    assert st_empty["total"] == 0
    assert st_empty["null_pct"] == 0.0
    assert st_empty["min"] is None

    # Mixed list with nulls
    vals = [10.0, None, 20.0, None, 30.0]
    st = compute_metric_stats(vals)
    assert st["total"] == 5
    assert st["non_null_count"] == 3
    assert st["null_count"] == 2
    assert st["null_pct"] == 40.0
    assert st["min"] == 10.0
    assert st["median"] == 20.0
    assert st["max"] == 30.0


def test_empty_database_report():
    """Verify that generating a report on an empty database runs cleanly without exceptions."""
    db = Database(":memory:")
    report = generate_data_quality_report(db)

    assert report["windows_15min_count"] == 0
    assert report["rollups_daily_count"] == 0
    assert report["days_collected"]["count"] == 0
    assert report["impossible_values"]["clean"] is True
    assert report["impossible_values"]["count"] == 0
    assert report["telemetry_health"]["dropped_events_count"] == 0
    assert report["telemetry_health"]["gaps"]["unknown"]["count"] == 0

    text = format_report_text(report)
    assert "EDC DATA QUALITY REPORT" in text
    assert "CLEAN (0 impossible values detected)" in text


def test_populated_database_report():
    """Verify reporting on a database containing 15-min and daily rollups and gaps."""
    db = Database(":memory:")
    t0 = datetime(2026, 11, 15, 10, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(minutes=15)
    t2 = t1 + timedelta(minutes=15)

    blocks = WindowBlocks(
        n_char=200,
        n_backspace=10,
        covered_s=900.0,
        idle_s=100.0,
        active_minutes=12,
        active_typing_s=180.0,
        display_scale=1.0,
    )

    r1 = Rollup15Min(
        schema_version="1.0.0",
        agent_version="0.1.0",
        window_start=t0,
        window_end=t1,
        coverage_ratio=0.95,
        low_coverage=False,
        day_of_week=6,
        is_weekend=True,
        hour_of_day=15,
        decimal_hour=15.5,
        blocks=blocks,
        gross_wpm=66.67,
        net_wpm=63.33,
    )
    r2 = Rollup15Min(
        schema_version="1.0.0",
        agent_version="0.1.0",
        window_start=t1,
        window_end=t2,
        coverage_ratio=0.85,
        low_coverage=False,
        day_of_week=6,
        is_weekend=True,
        hour_of_day=15,
        decimal_hour=15.75,
        blocks=blocks,
        gross_wpm=55.0,
        net_wpm=52.0,
    )

    db.insert_rollup_15min(r1)
    db.insert_rollup_15min(r2)

    daily = RollupDaily(
        schema_version="1.0.0",
        agent_version="0.1.0",
        logical_day=date(2026, 11, 15),
        day_of_week=6,
        is_weekend=True,
        coverage_ratio=0.90,
        low_coverage=False,
        after_hours_active_minutes=30.0,
        after_hours_ratio=0.25,
        late_night_flag=False,
        avg_session_duration_mins=25.0,
        max_session_duration_mins=60.0,
    )
    db.insert_rollup_daily(daily)

    # Log telemetry events and gaps
    db.set_dropped_events_count(5)
    db.insert_gap_log(t0, t1, 900.0, "unknown")
    db.insert_gap_log(t1, t2, 900.0, "idle")

    report = generate_data_quality_report(db)

    assert report["windows_15min_count"] == 2
    assert report["rollups_daily_count"] == 1
    assert report["days_collected"]["count"] == 1
    assert "2026-11-15" in report["days_collected"]["days"]
    assert report["telemetry_health"]["dropped_events_count"] == 5
    assert report["telemetry_health"]["gaps"]["unknown"]["count"] == 1
    assert report["telemetry_health"]["gaps"]["idle"]["count"] == 1
    assert report["impossible_values"]["clean"] is True

    # Check metrics stats
    wpm_stat = report["metrics_15min"]["gross_wpm"]
    assert wpm_stat["total"] == 2
    assert wpm_stat["min"] == 55.0
    assert wpm_stat["max"] == 66.67


def test_impossible_values_detection():
    """Verify that WPM > 250, negative durations, and invalid ratios are flagged."""
    t0 = datetime(2026, 11, 15, 10, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(minutes=15)

    blocks = WindowBlocks(
        n_char=200,
        covered_s=900.0,
        idle_s=100.0,
        active_minutes=12,
        active_typing_s=180.0,
        display_scale=1.0,
    )

    # Rollup with impossible WPM and impossible ratio
    bad_r = Rollup15Min(
        schema_version="1.0.0",
        agent_version="0.1.0",
        window_start=t0,
        window_end=t1,
        coverage_ratio=1.5,  # Invalid ratio > 1.0!
        low_coverage=False,
        day_of_week=6,
        is_weekend=True,
        hour_of_day=15,
        decimal_hour=15.5,
        blocks=blocks,
        gross_wpm=320.0,  # Impossible human WPM > 250!
        net_wpm=310.0,
    )

    bad_daily = RollupDaily(
        schema_version="1.0.0",
        agent_version="0.1.0",
        logical_day=date(2026, 11, 15),
        day_of_week=6,
        is_weekend=True,
        coverage_ratio=0.90,
        low_coverage=False,
        avg_session_duration_mins=-12.0,  # Negative duration!
    )

    violations = find_impossible_values([bad_r], [bad_daily])
    assert len(violations) >= 3

    metrics_violated = {v["metric"] for v in violations}
    assert "gross_wpm" in metrics_violated
    assert "net_wpm" in metrics_violated
    assert "coverage_ratio" in metrics_violated
    assert "avg_session_duration_mins" in metrics_violated
