"""Data Quality Report for Employee Data Collector (EDC).

Per Prompt 14:
- Days collected and coverage per day.
- % null per metric across 15-minute and daily rollups.
- min/median/max per numeric metric.
- Impossible values detection (WPM above 250, negative durations, out-of-range ratios).
- Counts of dropped events and unknown gaps.

Supports standalone execution (`python scripts/data_quality_report.py --db PATH`)
and programmatic invocation (`generate_data_quality_report(db)`).
"""
import argparse
from datetime import date
import json
from pathlib import Path
import statistics
import sys
from typing import Any, Dict, List, Optional, Tuple, Union

# Ensure agent and shared packages are on path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "agent"))
sys.path.insert(0, str(REPO_ROOT / "shared"))

from edc_agent.privacy.export import load_registry_columns
from edc_agent.storage.database import Database
from edc_schemas import Rollup15Min, RollupDaily


def get_default_db_path() -> Path:
    return Path.home() / ".edc" / "agent.db"


def compute_metric_stats(values: List[Any]) -> Dict[str, Any]:
    """Compute null percentage and min/median/max for a sequence of observations."""
    total = len(values)
    if total == 0:
        return {
            "total": 0,
            "non_null_count": 0,
            "null_count": 0,
            "null_pct": 0.0,
            "min": None,
            "median": None,
            "max": None,
        }

    non_nulls = [v for v in values if v is not None]
    null_count = total - len(non_nulls)
    null_pct = (null_count / total) * 100.0

    numeric_vals = [
        float(v) for v in non_nulls
        if isinstance(v, (int, float)) and not isinstance(v, bool)
    ]

    min_val: Optional[float] = None
    median_val: Optional[float] = None
    max_val: Optional[float] = None

    if numeric_vals:
        min_val = min(numeric_vals)
        median_val = statistics.median(numeric_vals)
        max_val = max(numeric_vals)

    return {
        "total": total,
        "non_null_count": len(non_nulls),
        "null_count": null_count,
        "null_pct": round(null_pct, 2),
        "min": round(min_val, 4) if min_val is not None else None,
        "median": round(median_val, 4) if median_val is not None else None,
        "max": round(max_val, 4) if max_val is not None else None,
    }


def find_impossible_values(
    rollups_15min: List[Rollup15Min],
    rollups_daily: List[RollupDaily],
) -> List[Dict[str, Any]]:
    """Detect impossible values (WPM > 250, negative durations, out-of-range ratios)."""
    violations: List[Dict[str, Any]] = []

    # 1. 15-Minute Rollup Checks
    for r in rollups_15min:
        w_id = f"15min:{r.window_start.isoformat()}"

        # WPM checks (WPM > 250 or < 0)
        if r.gross_wpm is not None:
            if r.gross_wpm > 250.0 or r.gross_wpm < 0.0:
                violations.append({
                    "record_id": w_id,
                    "level": "15min",
                    "metric": "gross_wpm",
                    "value": r.gross_wpm,
                    "reason": "WPM > 250 or negative",
                })
        if r.net_wpm is not None:
            if r.net_wpm > 250.0 or r.net_wpm < 0.0:
                violations.append({
                    "record_id": w_id,
                    "level": "15min",
                    "metric": "net_wpm",
                    "value": r.net_wpm,
                    "reason": "WPM > 250 or negative",
                })

        # Negative duration checks
        durations_to_check = {
            "active_typing_s": r.blocks.active_typing_s if r.blocks else None,
            "idle_s": r.blocks.idle_s if r.blocks else None,
            "pointer_idle_s": r.pointer_idle_s,
            "short_idle_total_s": r.short_idle_total_s,
            "mean_flight_time_ms": r.mean_flight_time_ms,
            "average_interval_seconds": r.average_interval_seconds,
            "pause_before_correction_ms": r.pause_before_correction_ms,
            "flight_time_sum_ms": r.blocks.flight_time_sum_ms if r.blocks else None,
        }
        for name, val in durations_to_check.items():
            if val is not None and val < 0.0:
                violations.append({
                    "record_id": w_id,
                    "level": "15min",
                    "metric": name,
                    "value": val,
                    "reason": "Negative duration",
                })

        # Ratio validity [0.0, 1.0]
        ratios_to_check = {
            "coverage_ratio": r.coverage_ratio,
            "active_typing_ratio": r.active_typing_ratio,
            "backspace_ratio": r.backspace_ratio,
            "correction_ratio": r.correction_ratio,
            "error_correction_efficiency": r.error_correction_efficiency,
        }
        for name, val in ratios_to_check.items():
            if val is not None and (val < 0.0 or val > 1.0):
                violations.append({
                    "record_id": w_id,
                    "level": "15min",
                    "metric": name,
                    "value": val,
                    "reason": "Ratio outside [0.0, 1.0]",
                })

    # 2. Daily Rollup Checks
    for d in rollups_daily:
        d_id = f"daily:{d.logical_day.isoformat()}"

        # Negative duration checks
        daily_durations = {
            "avg_session_duration_mins": d.avg_session_duration_mins,
            "max_session_duration_mins": d.max_session_duration_mins,
            "avg_break_duration_mins": d.avg_break_duration_mins,
            "longest_stretch_duration_mins": d.longest_stretch_duration_mins,
            "post_stretch_break_mins": d.post_stretch_break_mins,
            "longest_lunch_break_mins": d.longest_lunch_break_mins,
            "avg_focus_block_mins": d.avg_focus_block_mins,
            "max_focus_block_mins": d.max_focus_block_mins,
            "total_focus_time_hours": d.total_focus_time_hours,
            "after_hours_active_minutes": d.after_hours_active_minutes,
        }
        for name, val in daily_durations.items():
            if val is not None and val < 0.0:
                violations.append({
                    "record_id": d_id,
                    "level": "daily",
                    "metric": name,
                    "value": val,
                    "reason": "Negative duration",
                })

        # Ratio validity [0.0, 1.0]
        daily_ratios = {
            "coverage_ratio": d.coverage_ratio,
            "after_hours_ratio": d.after_hours_ratio,
            "after_hours_ratio_7d_avg": d.after_hours_ratio_7d_avg,
        }
        for name, val in daily_ratios.items():
            if val is not None and (val < 0.0 or val > 1.0):
                violations.append({
                    "record_id": d_id,
                    "level": "daily",
                    "metric": name,
                    "value": val,
                    "reason": "Ratio outside [0.0, 1.0]",
                })

    return violations


def generate_data_quality_report(db: Database) -> Dict[str, Any]:
    """Generate comprehensive data quality report dict from local EDC database."""
    rollups_15min = db.get_all_rollups_15min()
    rollups_daily = db.get_all_rollups_daily()

    # 1. Days collected
    daily_days = [d.logical_day.isoformat() for d in rollups_daily]
    min_days_set = {r.window_start.date().isoformat() for r in rollups_15min}
    all_days = sorted(list(set(daily_days).union(min_days_set)))

    # 2. Coverage per day
    coverage_by_day: Dict[str, Dict[str, Any]] = {}
    for d in rollups_daily:
        coverage_by_day[d.logical_day.isoformat()] = {
            "coverage_ratio": round(float(d.coverage_ratio), 4),
            "low_coverage": bool(d.low_coverage),
        }

    # Include days where only 15-min rollups exist
    for r in rollups_15min:
        d_str = r.window_start.date().isoformat()
        if d_str not in coverage_by_day:
            coverage_by_day[d_str] = {
                "coverage_ratio": round(float(r.coverage_ratio), 4),
                "low_coverage": bool(r.low_coverage),
            }

    daily_cov_vals = [c["coverage_ratio"] for c in coverage_by_day.values()]
    cov_summary = {
        "mean_coverage": round(statistics.mean(daily_cov_vals), 4) if daily_cov_vals else 0.0,
        "min_coverage": min(daily_cov_vals) if daily_cov_vals else 0.0,
        "median_coverage": round(statistics.median(daily_cov_vals), 4) if daily_cov_vals else 0.0,
        "max_coverage": max(daily_cov_vals) if daily_cov_vals else 0.0,
    }

    # 3. % null and min/median/max per metric
    cols_15min, cols_daily = load_registry_columns()

    # Fallback to model field names if registry missing
    if not cols_15min:
        cols_15min = [f for f in Rollup15Min.model_fields.keys() if f not in ("schema_version", "agent_version", "blocks")]
    if not cols_daily:
        cols_daily = [f for f in RollupDaily.model_fields.keys() if f not in ("schema_version", "agent_version")]

    metrics_15min_stats: Dict[str, Dict[str, Any]] = {}
    for col in cols_15min:
        vals = [getattr(r, col, None) for r in rollups_15min]
        metrics_15min_stats[col] = compute_metric_stats(vals)

    metrics_daily_stats: Dict[str, Dict[str, Any]] = {}
    for col in cols_daily:
        vals = [getattr(d, col, None) for d in rollups_daily]
        metrics_daily_stats[col] = compute_metric_stats(vals)

    # 4. Impossible values
    violations = find_impossible_values(rollups_15min, rollups_daily)

    # 5. Counts of dropped events and unknown gaps
    dropped_events_count = db.get_dropped_events_count()

    gap_rows = db.get_gap_logs()
    unknown_gaps = [g for g in gap_rows if g["gap_type"] == "unknown"]
    away_gaps = [g for g in gap_rows if g["gap_type"] == "away"]
    idle_gaps = [g for g in gap_rows if g["gap_type"] == "idle"]

    unknown_duration_s = sum(g["duration_s"] for g in unknown_gaps)
    away_duration_s = sum(g["duration_s"] for g in away_gaps)
    idle_duration_s = sum(g["duration_s"] for g in idle_gaps)

    return {
        "db_path": db.db_path,
        "windows_15min_count": len(rollups_15min),
        "rollups_daily_count": len(rollups_daily),
        "days_collected": {
            "count": len(all_days),
            "days": all_days,
        },
        "coverage_per_day": {
            "by_day": coverage_by_day,
            "summary": cov_summary,
        },
        "metrics_15min": metrics_15min_stats,
        "metrics_daily": metrics_daily_stats,
        "impossible_values": {
            "count": len(violations),
            "clean": len(violations) == 0,
            "violations": violations,
        },
        "telemetry_health": {
            "dropped_events_count": dropped_events_count,
            "gaps": {
                "unknown": {
                    "count": len(unknown_gaps),
                    "total_duration_s": round(unknown_duration_s, 2),
                },
                "away": {
                    "count": len(away_gaps),
                    "total_duration_s": round(away_duration_s, 2),
                },
                "idle": {
                    "count": len(idle_gaps),
                    "total_duration_s": round(idle_duration_s, 2),
                },
            },
        },
    }


def format_report_text(report: Dict[str, Any], verbose: bool = False) -> str:
    """Format report dict as a clean, human-readable terminal dashboard."""
    lines: List[str] = []
    w = 78

    lines.append("=" * w)
    lines.append(f"{'EDC DATA QUALITY REPORT':^{w}}")
    lines.append("=" * w)

    # Overview
    days_data = report["days_collected"]
    cov_data = report["coverage_per_day"]
    lines.append(f"Database:            {report['db_path']}")
    lines.append(f"15-Min Windows:      {report['windows_15min_count']}")
    lines.append(f"Daily Rollups:       {report['rollups_daily_count']}")
    lines.append(f"Total Days Tracked:  {days_data['count']} {days_data['days']}")
    lines.append("-" * w)

    # Coverage summary
    s = cov_data["summary"]
    lines.append(f"Coverage Summary:    Mean: {s['mean_coverage']:.1%} | Min: {s['min_coverage']:.1%} | Median: {s['median_coverage']:.1%} | Max: {s['max_coverage']:.1%}")
    lines.append("-" * w)
    lines.append(f"{'Date':<14} | {'Coverage':<12} | {'Low Coverage':<14}")
    lines.append("-" * w)
    for day, info in cov_data["by_day"].items():
        low_str = "YES (Warning)" if info["low_coverage"] else "No"
        lines.append(f"{day:<14} | {info['coverage_ratio']:<11.1%} | {low_str:<14}")
    lines.append("-" * w)

    # Telemetry Health: Dropped Events & Gaps
    th = report["telemetry_health"]
    gaps = th["gaps"]
    lines.append(f"Dropped Events:      {th['dropped_events_count']}")
    lines.append(f"Unknown Gaps:        {gaps['unknown']['count']} ({gaps['unknown']['total_duration_s']:.1f} s total)")
    lines.append(f"Away Gaps:           {gaps['away']['count']} ({gaps['away']['total_duration_s']:.1f} s total)")
    lines.append(f"Idle Gaps:           {gaps['idle']['count']} ({gaps['idle']['total_duration_s']:.1f} s total)")
    lines.append("-" * w)

    # Impossible values check
    iv = report["impossible_values"]
    if iv["clean"]:
        lines.append(f"Impossible Values:   CLEAN (0 impossible values detected)")
    else:
        lines.append(f"Impossible Values:   WARNING! {iv['count']} VIOLATION(S) FOUND:")
        for v in iv["violations"]:
            lines.append(f"  - [{v['level']}] {v['record_id']} | {v['metric']} = {v['value']}: {v['reason']}")
    lines.append("-" * w)

    # Metrics summary table (15-min and daily)
    lines.append(f"{'15-MIN METRICS (SAMPLE)':<30} | {'Null %':<8} | {'Min':<10} | {'Median':<10} | {'Max':<10}")
    lines.append("-" * w)
    items_15 = list(report["metrics_15min"].items())
    display_15 = items_15 if verbose else items_15[:10]
    for col, st in display_15:
        min_s = f"{st['min']:.2f}" if st["min"] is not None else "-"
        med_s = f"{st['median']:.2f}" if st["median"] is not None else "-"
        max_s = f"{st['max']:.2f}" if st["max"] is not None else "-"
        lines.append(f"{col:<30} | {st['null_pct']:>6.1f}% | {min_s:>10} | {med_s:>10} | {max_s:>10}")

    if not verbose and len(items_15) > 10:
        lines.append(f"... and {len(items_15) - 10} more 15-min metrics (run with --verbose to view all)")

    lines.append("-" * w)
    lines.append(f"{'DAILY METRICS (SAMPLE)':<30} | {'Null %':<8} | {'Min':<10} | {'Median':<10} | {'Max':<10}")
    lines.append("-" * w)
    items_d = list(report["metrics_daily"].items())
    display_d = items_d if verbose else items_d[:10]
    for col, st in display_d:
        min_s = f"{st['min']:.2f}" if st["min"] is not None else "-"
        med_s = f"{st['median']:.2f}" if st["median"] is not None else "-"
        max_s = f"{st['max']:.2f}" if st["max"] is not None else "-"
        lines.append(f"{col:<30} | {st['null_pct']:>6.1f}% | {min_s:>10} | {med_s:>10} | {max_s:>10}")

    if not verbose and len(items_d) > 10:
        lines.append(f"... and {len(items_d) - 10} more daily metrics (run with --verbose to view all)")

    lines.append("=" * w)
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate data quality report from EDC SQLite database.")
    parser.add_argument("--db", type=str, default=None, help="Path to SQLite database (default: ~/.edc/agent.db)")
    parser.add_argument("--json", action="store_true", help="Output full report as formatted JSON")
    parser.add_argument("--verbose", action="store_true", help="Display all metric rows without truncation")
    args = parser.parse_args()

    db_path = Path(args.db) if args.db else get_default_db_path()
    if not db_path.exists():
        sys.stderr.write(f"[ERROR] Database file not found at {db_path}\n")
        return 1

    db = Database(db_path)
    report = generate_data_quality_report(db)

    if args.json:
        sys.stdout.write(json.dumps(report, indent=2) + "\n")
    else:
        sys.stdout.write(format_report_text(report, verbose=args.verbose) + "\n")

    # Exit code: 0 if clean, 1 if impossible values detected
    return 0 if report["impossible_values"]["clean"] else 1


if __name__ == "__main__":
    sys.exit(main())
