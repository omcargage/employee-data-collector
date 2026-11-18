"""Machine learning subpackage for WorkSense per-person normalization, temporal neural networks, and inference."""
from .dataset import WorkSenseDataset, prepare_dataloaders, split_employees
from .exporter import export_ml_dataset, prepare_ml_records_from_database
from .features import (
    CATEGORY_MAPPINGS,
    CORE_NUMERICAL_FEATURES,
    INT_TO_STATUS,
    STATUS_TO_INT,
    BaselineStats,
    PersonalBaselineTransformer,
)
from .network import WorkSenseTemporalNN
from .normalisation import (
    compute_median_and_mad,
    compute_rolling_median_mad,
    normalize_features_per_person,
    robust_zscore,
)
from .predictor import WorkSenseBurnoutPredictor
from .splitting import group_kfold_by_person, split_by_person
from .trainer import TrainingMetrics, WorkSenseTrainer

__all__ = [
    "compute_median_and_mad",
    "compute_rolling_median_mad",
    "robust_zscore",
    "normalize_features_per_person",
    "split_by_person",
    "group_kfold_by_person",
    "prepare_ml_records_from_database",
    "export_ml_dataset",
    "CATEGORY_MAPPINGS",
    "CORE_NUMERICAL_FEATURES",
    "STATUS_TO_INT",
    "INT_TO_STATUS",
    "BaselineStats",
    "PersonalBaselineTransformer",
    "WorkSenseTemporalNN",
    "WorkSenseDataset",
    "split_employees",
    "prepare_dataloaders",
    "WorkSenseTrainer",
    "TrainingMetrics",
    "WorkSenseBurnoutPredictor",
]
