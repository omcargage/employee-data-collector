"""Comprehensive test suite for Activity Pattern Validation, Per-Person Rolling Median/MAD Normalization, and Split-by-Person Helper."""
import csv
from pathlib import Path
import pytest

from edc_agent.ml import (
    compute_median_and_mad,
    compute_rolling_median_mad,
    export_ml_dataset,
    group_kfold_by_person,
    normalize_features_per_person,
    robust_zscore,
    split_by_person,
)
from edc_agent.validation import (
    evaluate_heavy_corrections,
    evaluate_mouse_jitter,
    evaluate_typing_speed,
    run_all_validation_checks,
)


# ==============================================================================
# 1. Activity Pattern Validation Tests
# ==============================================================================

def test_typing_speed_pattern_shifts_metrics():
    """Fast typing must produce higher WPM and lower flight time than slow typing."""
    res = evaluate_typing_speed(fast_wpm=85.0, slow_wpm=25.0)

    assert res["passed"] is True
    assert res["wpm_difference"] > 40.0
    assert res["fast"]["measured_wpm"] > res["slow"]["measured_wpm"]
    assert res["fast"]["mean_flight_time_ms"] < res["slow"]["mean_flight_time_ms"]
    assert res["flight_ratio"] > 2.0


def test_heavy_corrections_pattern_shifts_metrics():
    """Frequent backspacing must significantly increase correction count and ratio."""
    res = evaluate_heavy_corrections(n_words=30)

    assert res["passed"] is True
    assert res["corrections_increase"] > 30
    assert res["ratio_increase"] > 0.20
    assert res["heavy"]["backspace_count"] > res["clean"]["backspace_count"]
    assert res["heavy"]["correction_ratio"] > res["clean"]["correction_ratio"]


def test_mouse_jitter_pattern_shifts_metrics():
    """Mouse jitter must significantly increase pointer distance, speed, and acceleration."""
    res = evaluate_mouse_jitter(duration_s=25.0)

    assert res["passed"] is True
    assert res["speed_ratio"] > 10.0
    assert res["distance_ratio"] > 10.0
    assert res["jitter"]["average_speed_px_s"] > res["smooth"]["average_speed_px_s"]
    assert res["jitter"]["mouse_distance_px"] > res["smooth"]["mouse_distance_px"]
    assert res["jitter"]["average_abs_accel_px_s2"] > res["smooth"]["average_abs_accel_px_s2"]


def test_run_all_validation_checks_suite():
    """All scripted validation patterns must pass simultaneously."""
    res = run_all_validation_checks()
    assert res["all_passed"] is True


# ==============================================================================
# 2. Rolling Median / MAD & Per-Person Normalization Tests
# ==============================================================================

def test_median_and_mad_hand_computed():
    """Verify median and MAD against hand-computed ground truth."""
    # Values: [10, 20, 30, 40, 50]
    # Median = 30.0
    # Absolute deviations: [20, 10, 0, 10, 20] -> sorted [0, 10, 10, 20, 20]
    # Median deviation = 10.0
    data = [10.0, 20.0, 30.0, 40.0, 50.0]
    med, mad = compute_median_and_mad(data)

    assert med == 30.0
    assert mad == 10.0


def test_rolling_median_mad_causal_window():
    """Rolling window must be strictly causal (no future peeking) and respect lookback bounds."""
    series = [10.0, 20.0, 30.0, 100.0, 20.0]
    # Window size 3:
    # i=0: [10] -> min_periods=2 -> None
    # i=1: [10, 20] -> median 15.0, mad 5.0
    # i=2: [10, 20, 30] -> median 20.0, mad 10.0
    # i=3: [20, 30, 100] -> median 30.0, mad 10.0
    # i=4: [30, 100, 20] -> sorted [20, 30, 100] -> median 30.0, mad 10.0
    meds, mads = compute_rolling_median_mad(series, window_size=3, min_periods=2)

    assert meds[0] is None
    assert meds[1] == 15.0
    assert meds[2] == 20.0
    assert meds[3] == 30.0
    assert meds[4] == 30.0


def test_robust_zscore_properties():
    """Robust z-score scaling properties."""
    # When value equals median, z-score is exactly 0.0
    assert robust_zscore(50.0, 50.0, 10.0) == 0.0

    # Above median -> positive z-score
    z_pos = robust_zscore(65.0, 50.0, 10.0)
    assert z_pos is not None and z_pos > 0.0

    # Below median -> negative z-score
    z_neg = robust_zscore(35.0, 50.0, 10.0)
    assert z_neg is not None and z_neg < 0.0

    # Zero MAD (constant value) does not divide by zero
    z_constant = robust_zscore(50.0, 50.0, 0.0)
    assert z_constant == 0.0


def test_per_person_normalization_isolation():
    """Normalization must preserve subject isolation: Alice's baseline must not affect Bob."""
    records = [
        # Alice: high typing baseline (~80 WPM)
        {"person_id": "Alice", "timestamp": "2026-11-01T10:00:00Z", "gross_wpm": 80.0},
        {"person_id": "Alice", "timestamp": "2026-11-02T10:00:00Z", "gross_wpm": 82.0},
        {"person_id": "Alice", "timestamp": "2026-11-03T10:00:00Z", "gross_wpm": 85.0},
        # Bob: slow typing baseline (~30 WPM)
        {"person_id": "Bob", "timestamp": "2026-11-01T10:00:00Z", "gross_wpm": 30.0},
        {"person_id": "Bob", "timestamp": "2026-11-02T10:00:00Z", "gross_wpm": 32.0},
        {"person_id": "Bob", "timestamp": "2026-11-03T10:00:00Z", "gross_wpm": 35.0},
    ]

    norm = normalize_features_per_person(
        records=records,
        person_col="person_id",
        feature_cols=["gross_wpm"],
        sort_col="timestamp",
        window_size=7,
        min_periods=2,
    )

    alice_rows = [r for r in norm if r["person_id"] == "Alice"]
    bob_rows = [r for r in norm if r["person_id"] == "Bob"]

    # Alice's median is ~81-82, not mixed with Bob's 30
    assert alice_rows[-1]["gross_wpm_median"] >= 80.0
    # Bob's median is ~31-32
    assert bob_rows[-1]["gross_wpm_median"] <= 35.0


# ==============================================================================
# 3. Split-by-Person Helper Tests
# ==============================================================================

def test_split_by_person_zero_subject_leakage():
    """Group-based splitting guarantees 100% disjoint persons between train and test."""
    records = []
    # 5 persons with 10 records each
    for pid in ["E101", "E102", "E103", "E104", "E105"]:
        for i in range(10):
            records.append({
                "person_id": pid,
                "timestamp": f"2026-11-{i+1:02d}T10:00:00Z",
                "gross_wpm": 50.0 + i,
            })

    train_recs, test_recs = split_by_person(
        records=records,
        person_col="person_id",
        test_size=0.4,  # 2 test subjects, 3 train subjects
        seed=42,
    )

    train_pids = {r["person_id"] for r in train_recs}
    test_pids = {r["person_id"] for r in test_recs}

    # Strict zero leakage assertion:
    assert train_pids.isdisjoint(test_pids), "Subjects leaked across train/test splits!"
    assert len(train_pids) == 3
    assert len(test_pids) == 2
    assert len(train_recs) == 30
    assert len(test_recs) == 20
    assert all(r["split"] == "train" for r in train_recs)
    assert all(r["split"] == "test" for r in test_recs)


def test_group_kfold_by_person():
    """K-Fold cross validation partitioned by person."""
    records = []
    # 4 distinct persons
    for pid in ["P1", "P2", "P3", "P4"]:
        for i in range(5):
            records.append({"person_id": pid, "timestamp": f"2026-11-0{i+1}", "val": i * 10})

    folds = list(group_kfold_by_person(records, person_col="person_id", n_splits=4, seed=123))
    assert len(folds) == 4

    for fold_idx, (train_f, val_f) in enumerate(folds):
        train_p = {r["person_id"] for r in train_f}
        val_p = {r["person_id"] for r in val_f}

        assert train_p.isdisjoint(val_p)
        assert len(val_p) == 1
        assert len(train_p) == 3
        assert all(r["split"] == "train" for r in train_f)
        assert all(r["split"] == "val" for r in val_f)


# ==============================================================================
# 4. ML Dataset Exporter Tests
# ==============================================================================

def test_export_ml_dataset_generates_valid_csv(tmp_path: Path):
    """Verify export_ml_dataset writes normalized features, joined labels, and split indicators."""
    records = []
    for pid in ["EMP-A", "EMP-B", "EMP-C"]:
        for d in range(1, 6):
            records.append({
                "person_id": pid,
                "timestamp": f"2026-11-0{d}T09:00:00Z",
                "gross_wpm": 60.0 + d * 2,
                "mouse_speed": 100.0 + d * 10,
                "stress": 3 if d % 2 == 0 else 2,
                "energy": 4,
                "workload": 3,
            })

    csv_path = tmp_path / "test_ml_export.csv"
    out_file, stats = export_ml_dataset(
        records=records,
        output_csv_path=csv_path,
        person_col="person_id",
        window_size=3,
        test_size=0.33,
    )

    assert out_file.exists()
    assert stats["total_records"] == 15
    assert stats["n_persons"] == 3
    assert stats["train_records"] > 0
    assert stats["test_records"] > 0

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
        rows = list(reader)

        # Check required columns
        assert "person_id" in headers
        assert "timestamp" in headers
        assert "split" in headers
        assert "stress" in headers
        assert "gross_wpm_norm" in headers
        assert "gross_wpm_median" in headers
        assert "gross_wpm_mad" in headers

        # Check split tags
        splits = {row["split"] for row in rows}
        assert splits == {"train", "test"}
