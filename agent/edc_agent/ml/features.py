"""Feature definitions, category groupings, and personal baseline normalization for WorkSense."""
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple
import numpy as np
import pandas as pd

# WorkSense 4 Privacy-Preserving Categories
CATEGORY_MAPPINGS: Dict[str, List[str]] = {
    "boundary_erosion": [
        "total_msgs_sent",
        "msgs_sent_after_hours",
        "msgs_sent_late_night",
        "after_hours_active_minutes",
        "after_hours_ratio",
        "late_night_flag",
        "after_hours_ratio_7d_avg",
        "consecutive_after_hours_days",
    ],
    "work_pattern_changes": [
        "avg_session_duration_mins",
        "max_session_duration_mins",
        "total_breaks_count",
        "avg_break_duration_mins",
        "extended_sessions_count",
        "longest_stretch_duration_mins",
        "post_stretch_break_mins",
        "stretch_intensity_pct",
        "stretch_to_total_work_ratio",
    ],
    "recovery_deficit": [
        "lunch_active_mins",
        "longest_lunch_break_mins",
        "lunch_work_ratio",
        "lunch_skipped_flag",
    ],
    "cognitive_and_focus_fatigue": [
        "avg_focus_block_mins",
        "max_focus_block_mins",
        "deep_work_blocks_count",
        "total_focus_time_hours",
        "focus_fragmentation_ratio",
        "daily_mean_wpm",
        "daily_backspace_ratio",
        "daily_keystroke_flight_cv",
        "daily_aimless_scroll_index",
        "daily_mean_stare_duration_s",
    ],
}

# BAT-12 Survey Dimensions from Schaufeli et al.
BAT_METRIC_COLUMNS: List[str] = [
    "bat_q1", "bat_q2", "bat_q3", "bat_q4", "bat_q5", "bat_q6",
    "bat_q7", "bat_q8", "bat_q9", "bat_q10", "bat_q11", "bat_q12",
    "bat_exhaustion", "bat_mental_distance", "bat_emotional_impairment",
    "bat_cognitive_impairment", "bat_total_score", "bat_verified_stress_day",
]

# Ordered list of all 31 core numerical telemetry features
CORE_NUMERICAL_FEATURES: List[str] = [
    feat for cat_features in CATEGORY_MAPPINGS.values() for feat in cat_features
]

STATUS_TO_INT: Dict[str, int] = {
    "Green": 0,
    "Yellow": 1,
    "Orange": 2,
    "Red": 3,
}
INT_TO_STATUS: Dict[int, str] = {v: k for k, v in STATUS_TO_INT.items()}


@dataclass
class BaselineStats:
    """Stores personal median and MAD for an employee, plus BAT-12 calibration metrics."""
    medians: Dict[str, float]
    mads: Dict[str, float]
    sample_count: int
    bat_baseline_score: Optional[float] = None
    bat_baseline_exhaustion: Optional[float] = None
    bat_baseline_cognitive: Optional[float] = None
    bat_baseline_status: Optional[str] = None
    is_baseline_stressed: Optional[bool] = None


class PersonalBaselineTransformer:
    """Normalizes employee behavioral metrics against their personal 14-day baseline using Median and MAD.

    In WorkSense:
    - Days 1-14: Baseline calibration phase with daily BAT-12 survey check-ins.
    - Days 15+: Robust z-score deviation relative to individual's own baseline:
        z = (x - median_14d) / (1.4826 * MAD_14d + eps)
    """

    def __init__(
        self,
        features: Optional[List[str]] = None,
        baseline_days: int = 14,
        sequence_length: int = 7,
        eps: float = 1e-4,
        clip_range: Tuple[float, float] = (-5.0, 5.0),
    ):
        self.features = features or list(CORE_NUMERICAL_FEATURES)
        self.baseline_days = baseline_days
        self.sequence_length = sequence_length
        self.eps = eps
        self.clip_min, self.clip_max = clip_range
        self.baselines: Dict[str, BaselineStats] = {}

    def fit_employee_baseline(self, employee_df: pd.DataFrame) -> Optional[BaselineStats]:
        """Fit personal baseline from the first `baseline_days` observations of an employee."""
        df_sorted = employee_df.sort_values("date").reset_index(drop=True)
        if len(df_sorted) < self.baseline_days:
            return None

        baseline_df = df_sorted.iloc[: self.baseline_days]
        medians: Dict[str, float] = {}
        mads: Dict[str, float] = {}

        for col in self.features:
            if col in baseline_df.columns:
                series = pd.to_numeric(baseline_df[col], errors="coerce").dropna()
                if len(series) > 0:
                    med = float(series.median())
                    mad = float((series - med).abs().median())
                else:
                    med = 0.0
                    mad = 1.0
            else:
                med = 0.0
                mad = 1.0

            medians[col] = med
            mads[col] = mad

        # Fit BAT-12 psychological baseline if available
        bat_score = None
        bat_ex = None
        bat_cog = None
        bat_status = None
        is_stressed = None

        if "bat_total_score" in baseline_df.columns:
            bat_series = pd.to_numeric(baseline_df["bat_total_score"], errors="coerce").dropna()
            if len(bat_series) > 0:
                bat_score = round(float(bat_series.mean()), 2)
                if bat_score >= 3.65:
                    bat_status = "Red"
                elif bat_score >= 3.02:
                    bat_status = "Orange"
                elif bat_score >= 2.59:
                    bat_status = "Yellow"
                else:
                    bat_status = "Green"
                is_stressed = bool(bat_score >= 2.59)

        if "bat_exhaustion" in baseline_df.columns:
            ex_series = pd.to_numeric(baseline_df["bat_exhaustion"], errors="coerce").dropna()
            if len(ex_series) > 0:
                bat_ex = round(float(ex_series.mean()), 2)

        if "bat_cognitive_impairment" in baseline_df.columns:
            cog_series = pd.to_numeric(baseline_df["bat_cognitive_impairment"], errors="coerce").dropna()
            if len(cog_series) > 0:
                bat_cog = round(float(cog_series.mean()), 2)

        stats = BaselineStats(
            medians=medians,
            mads=mads,
            sample_count=len(baseline_df),
            bat_baseline_score=bat_score,
            bat_baseline_exhaustion=bat_ex,
            bat_baseline_cognitive=bat_cog,
            bat_baseline_status=bat_status,
            is_baseline_stressed=is_stressed,
        )
        return stats

    def transform_employee(
        self,
        employee_df: pd.DataFrame,
        baseline: Optional[BaselineStats] = None,
    ) -> pd.DataFrame:
        """Transform employee dataframe adding personal normalized z-score columns."""
        df = employee_df.sort_values("date").copy().reset_index(drop=True)
        if baseline is None:
            baseline = self.fit_employee_baseline(df)

        if baseline is None:
            # Insufficient data
            for col in self.features:
                df[f"{col}_norm"] = np.nan
            return df

        for col in self.features:
            if col in df.columns:
                val = pd.to_numeric(df[col], errors="coerce")
                med = baseline.medians[col]
                mad = baseline.mads[col]
                denom = (1.4826 * mad) + self.eps
                z = (val - med) / denom
                df[f"{col}_norm"] = z.clip(self.clip_min, self.clip_max)
            else:
                df[f"{col}_norm"] = 0.0

        return df

    def extract_sequences(
        self,
        df: pd.DataFrame,
        target_col: str = "target_burnout_status_5d",
        risk_col: str = "target_burnout_risk_5d",
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, List[Dict[str, Any]]]:
        """Extract 7-day sliding window sequences and 5-day forward targets."""
        norm_cols = [f"{col}_norm" for col in self.features]
        X_list: List[np.ndarray] = []
        y_class_list: List[int] = []
        y_risk_list: List[float] = []
        meta_list: List[Dict[str, Any]] = []

        for emp_id, emp_df in df.groupby("employee_id"):
            emp_sorted = emp_df.sort_values("date").reset_index(drop=True)
            if len(emp_sorted) < (self.baseline_days + self.sequence_length):
                continue

            baseline = self.fit_employee_baseline(emp_sorted)
            if norm_cols[0] not in emp_sorted.columns:
                emp_sorted = self.transform_employee(emp_sorted, baseline=baseline)

            for end_idx in range(self.baseline_days, len(emp_sorted)):
                start_idx = end_idx - self.sequence_length + 1
                if start_idx < 0:
                    continue

                seq_df = emp_sorted.iloc[start_idx : end_idx + 1]
                target_row = emp_sorted.iloc[end_idx]

                status_str = target_row.get(target_col)
                if pd.isna(status_str) or status_str not in STATUS_TO_INT:
                    continue

                risk_val = target_row.get(risk_col)
                if pd.isna(risk_val):
                    continue

                seq_features = seq_df[norm_cols].to_numpy(dtype=np.float32)
                seq_features = np.nan_to_num(seq_features, nan=0.0)

                X_list.append(seq_features)
                y_class_list.append(STATUS_TO_INT[status_str])
                y_risk_list.append(float(risk_val))
                meta_list.append({
                    "employee_id": emp_id,
                    "date": str(target_row["date"]),
                    "cohort": target_row.get("cohort", "unknown"),
                    "profile": target_row.get("profile", "unknown"),
                    "current_status": target_row.get("current_burnout_status", "Green"),
                    "target_status": status_str,
                    "target_risk": float(risk_val),
                    "baseline_bat_score": baseline.bat_baseline_score if baseline else None,
                    "baseline_bat_status": baseline.bat_baseline_status if baseline else None,
                    "today_bat_score": float(target_row.get("bat_total_score", 0.0)) if "bat_total_score" in target_row else None,
                })

        if not X_list:
            n_feats = len(self.features)
            return (
                np.empty((0, self.sequence_length, n_feats), dtype=np.float32),
                np.empty((0,), dtype=np.int64),
                np.empty((0,), dtype=np.float32),
                [],
            )

        X = np.stack(X_list, axis=0)
        y_class = np.array(y_class_list, dtype=np.int64)
        y_risk = np.array(y_risk_list, dtype=np.float32)
        return X, y_class, y_risk, meta_list
