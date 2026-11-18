"""Unit tests for WorkSense machine learning pipeline, normalization, and temporal neural network."""
import numpy as np
import pandas as pd
import pytest
import torch

from edc_agent.ml import (
    CORE_NUMERICAL_FEATURES,
    PersonalBaselineTransformer,
    WorkSenseBurnoutPredictor,
    WorkSenseDataset,
    WorkSenseTemporalNN,
    WorkSenseTrainer,
    prepare_dataloaders,
    split_employees,
)


def _generate_synthetic_employee_history(
    employee_id: str = "EMP_TEST_001",
    n_days: int = 30,
    stress_trend: bool = False,
) -> pd.DataFrame:
    """Generate mock chronological telemetry dataframe for an employee."""
    dates = pd.date_range("2026-10-01", periods=n_days, freq="D").strftime("%Y-%m-%d").tolist()
    rows = []
    rng = np.random.default_rng(42)

    for i, dt in enumerate(dates):
        mult = (1.0 + (i / n_days) * 2.0) if stress_trend and i >= 14 else 1.0
        row = {
            "employee_id": employee_id,
            "cohort": "stressed" if stress_trend else "healthy",
            "profile": "stressed" if stress_trend else "healthy",
            "date": dt,
            "day_of_week": (i % 7),
            "is_weekend": 1 if (i % 7) in [5, 6] else 0,
            "target_burnout_status_5d": "Red" if stress_trend and i >= 20 else ("Yellow" if stress_trend else "Green"),
            "target_burnout_risk_5d": min(0.95, 0.2 * mult),
            "current_burnout_status": "Orange" if stress_trend and i >= 20 else "Green",
        }
        for feat in CORE_NUMERICAL_FEATURES:
            row[feat] = float(rng.uniform(10.0, 50.0) * mult)
        rows.append(row)

    return pd.DataFrame(rows)


def test_baseline_calibration_14_days():
    """Verify that fewer than 14 days yields insufficient data and baseline is computed on >=14 days."""
    transformer = PersonalBaselineTransformer(features=CORE_NUMERICAL_FEATURES, baseline_days=14)

    # 10 days of data
    df_10 = _generate_synthetic_employee_history(n_days=10)
    baseline_10 = transformer.fit_employee_baseline(df_10)
    assert baseline_10 is None, "Baseline should not fit on <14 days"

    # 20 days of data
    df_20 = _generate_synthetic_employee_history(n_days=20)
    baseline_20 = transformer.fit_employee_baseline(df_20)
    assert baseline_20 is not None
    assert baseline_20.sample_count == 14
    for feat in CORE_NUMERICAL_FEATURES:
        assert feat in baseline_20.medians
        assert feat in baseline_20.mads


def test_robust_zscore_clipping():
    """Verify robust z-score transformation and clipping bounds."""
    transformer = PersonalBaselineTransformer(features=CORE_NUMERICAL_FEATURES, baseline_days=14, clip_range=(-5.0, 5.0))
    df = _generate_synthetic_employee_history(n_days=25)

    norm_df = transformer.transform_employee(df)
    for feat in CORE_NUMERICAL_FEATURES:
        norm_col = f"{feat}_norm"
        assert norm_col in norm_df.columns
        assert norm_df[norm_col].min() >= -5.0
        assert norm_df[norm_col].max() <= 5.0


def test_split_by_person_zero_leakage():
    """Verify strict subject isolation between train, validation, and test splits."""
    employees = [f"EMP_{i:03d}" for i in range(1, 21)]
    records = []
    for emp in employees:
        emp_df = _generate_synthetic_employee_history(employee_id=emp, n_days=20)
        records.append(emp_df)
    full_df = pd.concat(records, ignore_index=True)

    train_df, val_df, test_df = split_employees(full_df, train_ratio=0.7, val_ratio=0.15, seed=42)

    train_pids = set(train_df["employee_id"].unique())
    val_pids = set(val_df["employee_id"].unique())
    test_pids = set(test_df["employee_id"].unique())

    assert len(train_pids) == 14
    assert len(val_pids) == 3
    assert len(test_pids) == 3

    assert train_pids.isdisjoint(val_pids), "Train and Val share employees!"
    assert train_pids.isdisjoint(test_pids), "Train and Test share employees!"
    assert val_pids.isdisjoint(test_pids), "Val and Test share employees!"


def test_temporal_nn_forward_pass():
    """Verify WorkSenseTemporalNN output shapes, probabilities, and temporal attention."""
    input_dim = len(CORE_NUMERICAL_FEATURES)
    model = WorkSenseTemporalNN(input_dim=input_dim, hidden_dim=32, num_classes=4)
    model.eval()

    batch_size = 4
    seq_len = 7
    x = torch.randn(batch_size, seq_len, input_dim)

    logits, risk, attn_weights = model(x)

    assert logits.shape == (batch_size, 4), f"Expected (4, 4), got {logits.shape}"
    assert risk.shape == (batch_size, 1), f"Expected (4, 1), got {risk.shape}"
    assert attn_weights.shape == (batch_size, seq_len), f"Expected (4, 7), got {attn_weights.shape}"

    # Attention weights must sum to 1.0 across the 7 timesteps
    attn_sums = attn_weights.sum(dim=-1).detach().numpy()
    np.testing.assert_allclose(attn_sums, 1.0, rtol=1e-5)

    # Risk must be strictly between 0.0 and 1.0 (Sigmoid)
    assert (risk >= 0.0).all() and (risk <= 1.0).all()


def test_explain_prediction_privacy_categories():
    """Verify that explain_prediction outputs the 4 privacy-preserving categories and no raw text."""
    input_dim = len(CORE_NUMERICAL_FEATURES)
    model = WorkSenseTemporalNN(input_dim=input_dim, hidden_dim=32, num_classes=4)
    model.eval()

    x_single = torch.randn(7, input_dim)
    attn = torch.softmax(torch.randn(7), dim=0)

    explanation = model.explain_prediction(x_single, attn)
    assert "category_attributions" in explanation
    assert "primary_drivers" in explanation

    cats = explanation["category_attributions"]
    assert "boundary_erosion" in cats
    assert "work_pattern_changes" in cats
    assert "recovery_deficit" in cats
    assert "cognitive_and_focus_fatigue" in cats

    # Check sum of attributions is approximately 100%
    total_pct = sum(cats.values())
    assert 99.0 <= total_pct <= 101.0, f"Expected total ~100%, got {total_pct}"


def test_predictor_insufficient_data_vs_active():
    """Verify predictor emits INSUFFICIENT_DATA before 14 days and full prediction afterwards."""
    input_dim = len(CORE_NUMERICAL_FEATURES)
    model = WorkSenseTemporalNN(input_dim=input_dim, hidden_dim=32, num_classes=4)
    transformer = PersonalBaselineTransformer(features=CORE_NUMERICAL_FEATURES, baseline_days=14)
    predictor = WorkSenseBurnoutPredictor(model=model, transformer=transformer)

    history_df = _generate_synthetic_employee_history(n_days=25, stress_trend=True)

    # 1. Under 14 days
    res_under = predictor.predict_daily(history_df.iloc[:8])
    assert res_under["status"] == "INSUFFICIENT_DATA"
    assert res_under["calibration_progress"]["days_collected"] == 8
    assert res_under["risk_score"] is None

    # 2. At 25 days (active prediction)
    res_active = predictor.predict_daily(history_df.iloc[:25])
    assert res_active["predicted_status_5d"] in ["Green", "Yellow", "Orange", "Red"]
    assert res_active["confidence"] is not None
    assert 0.0 <= res_active["risk_score"] <= 1.0
    assert len(res_active["temporal_attention"]) == 7
    assert len(res_active["category_attributions"]) == 4
