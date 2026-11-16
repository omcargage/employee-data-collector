"""Machine learning subpackage for robust per-person normalization and subject-grouped splitting."""
from .exporter import export_ml_dataset, prepare_ml_records_from_database
from .normalisation import (
    compute_median_and_mad,
    compute_rolling_median_mad,
    normalize_features_per_person,
    robust_zscore,
)
from .splitting import group_kfold_by_person, split_by_person

__all__ = [
    "compute_median_and_mad",
    "compute_rolling_median_mad",
    "robust_zscore",
    "normalize_features_per_person",
    "split_by_person",
    "group_kfold_by_person",
    "prepare_ml_records_from_database",
    "export_ml_dataset",
]
