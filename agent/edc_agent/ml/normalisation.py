"""Per-person feature normalization using rolling median and Median Absolute Deviation (MAD).

Applies robust z-score transformation:
    z_i = (x_i - median_w) / (1.4826 * MAD_w + eps)

Where median_w and MAD_w are computed strictly on the individual employee's
historical sliding window, avoiding subject contamination and outlier distortion.
"""
from collections import defaultdict
import math
import statistics
from typing import Any, Dict, List, Optional, Sequence, Tuple


def compute_median_and_mad(
    values: Sequence[float],
) -> Tuple[float, float]:
    """Compute the sample median and Median Absolute Deviation (MAD) of a numerical slice."""
    if not values:
        return 0.0, 0.0

    med = statistics.median(values)
    abs_deviations = [abs(v - med) for v in values]
    mad = statistics.median(abs_deviations)
    return med, mad


def compute_rolling_median_mad(
    values: Sequence[Optional[float]],
    window_size: int = 7,
    min_periods: int = 2,
) -> Tuple[List[Optional[float]], List[Optional[float]]]:
    """Compute causal rolling median and rolling MAD over a sliding lookback window.

    Causal: For observation at index i, the window includes values up to i (no future peeking).

    Args:
        values: Sequence of numerical values or None.
        window_size: Maximum lookback observations.
        min_periods: Minimum valid observations required to compute baseline.

    Returns:
        Tuple of (rolling_medians, rolling_mads).
    """
    medians: List[Optional[float]] = []
    mads: List[Optional[float]] = []

    for i in range(len(values)):
        # Lookback slice [max(0, i - window_size + 1) : i + 1]
        start_idx = max(0, i - window_size + 1)
        window_slice = [v for v in values[start_idx : i + 1] if v is not None and not math.isnan(v)]

        if len(window_slice) < min_periods:
            medians.append(None)
            mads.append(None)
        else:
            med, mad = compute_median_and_mad(window_slice)
            medians.append(med)
            mads.append(mad)

    return medians, mads


def robust_zscore(
    value: Optional[float],
    median: Optional[float],
    mad: Optional[float],
    scale_factor: float = 1.4826,
    eps: float = 1e-6,
) -> Optional[float]:
    """Compute robust z-score: (value - median) / (1.4826 * mad + eps)."""
    if value is None or median is None or mad is None:
        return None

    denom = (scale_factor * mad) + eps
    return (value - median) / denom


def normalize_features_per_person(
    records: List[Dict[str, Any]],
    person_col: str = "person_id",
    feature_cols: Optional[List[str]] = None,
    sort_col: str = "timestamp",
    window_size: int = 7,
    min_periods: int = 2,
) -> List[Dict[str, Any]]:
    """Apply per-person rolling median/MAD normalization across numerical features.

    Each individual's time series is normalized strictly against their own baseline.
    Adds `<col>_norm`, `<col>_median`, and `<col>_mad` to each record.

    Args:
        records: List of dictionary records containing features, person_col, and sort_col.
        person_col: Column identifying the individual (e.g. 'employee_code' or 'person_id').
        feature_cols: Numerical columns to normalize. If None, auto-detected.
        sort_col: Timestamp or sequence column used for chronological ordering.
        window_size: Sliding lookback window size.
        min_periods: Minimum observations for valid baseline.

    Returns:
        New list of dictionaries enriched with normalized features.
    """
    if not records:
        return []

    # 1. Group records by person
    person_groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in records:
        pid = str(r.get(person_col, "default"))
        person_groups[pid].append(dict(r))

    # Auto-detect numerical feature columns if not explicitly provided
    if feature_cols is None:
        first_row = records[0]
        feature_cols = [
            k for k, v in first_row.items()
            if isinstance(v, (int, float))
            and not isinstance(v, bool)
            and k not in (person_col, sort_col, "stress", "energy", "workload", "id")
        ]

    normalized_output: List[Dict[str, Any]] = []

    # 2. Process each person independently
    for pid, group in person_groups.items():
        # Sort chronologically
        group.sort(key=lambda x: str(x.get(sort_col, "")))

        # Normalize each feature
        for feat in feature_cols:
            raw_values = [
                float(row[feat]) if (row.get(feat) is not None and not isinstance(row.get(feat), str)) else None
                for row in group
            ]
            rolling_meds, rolling_mads = compute_rolling_median_mad(
                raw_values,
                window_size=window_size,
                min_periods=min_periods,
            )

            for idx, row in enumerate(group):
                val = raw_values[idx]
                med = rolling_meds[idx]
                mad = rolling_mads[idx]
                z = robust_zscore(val, med, mad)

                row[f"{feat}_norm"] = z
                row[f"{feat}_median"] = med
                row[f"{feat}_mad"] = mad

        normalized_output.extend(group)

    # Sort final output by original sort_col
    normalized_output.sort(key=lambda x: str(x.get(sort_col, "")))
    return normalized_output
