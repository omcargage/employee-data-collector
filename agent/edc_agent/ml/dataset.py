"""PyTorch Dataset and Split-by-Person DataLoaders for WorkSense ML."""
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import pandas as pd
import torch
from torch.utils.data import DataLoader, Dataset

from edc_agent.ml.features import PersonalBaselineTransformer, STATUS_TO_INT


class WorkSenseDataset(Dataset):
    """PyTorch Dataset holding temporal behavioral sequences and burnout targets."""

    def __init__(
        self,
        X: np.ndarray,
        y_class: np.ndarray,
        y_risk: np.ndarray,
        metadata: Optional[List[Dict[str, Any]]] = None,
    ):
        self.X = torch.tensor(X, dtype=torch.float32)
        self.y_class = torch.tensor(y_class, dtype=torch.long)
        self.y_risk = torch.tensor(y_risk, dtype=torch.float32).unsqueeze(-1)
        self.metadata = metadata or []

    def __len__(self) -> int:
        return len(self.X)

    def __getitem__(self, idx: int) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        return self.X[idx], self.y_class[idx], self.y_risk[idx]


def split_employees(
    df: pd.DataFrame,
    train_ratio: float = 0.70,
    val_ratio: float = 0.15,
    seed: int = 42,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Partition DataFrame into train, validation, and test splits strictly by employee_id.

    Guarantees 100% subject isolation (0% cross-split leakage).
    """
    unique_employees = sorted(df["employee_id"].unique().tolist())
    n_total = len(unique_employees)

    rng = np.random.default_rng(seed)
    shuffled = rng.permutation(unique_employees).tolist()

    n_train = int(round(n_total * train_ratio))
    n_val = int(round(n_total * val_ratio))

    train_ids = set(shuffled[:n_train])
    val_ids = set(shuffled[n_train : n_train + n_val])
    test_ids = set(shuffled[n_train + n_val :])

    # Assert no overlap
    assert train_ids.isdisjoint(val_ids)
    assert train_ids.isdisjoint(test_ids)
    assert val_ids.isdisjoint(test_ids)

    train_df = df[df["employee_id"].isin(train_ids)].copy()
    val_df = df[df["employee_id"].isin(val_ids)].copy()
    test_df = df[df["employee_id"].isin(test_ids)].copy()

    return train_df, val_df, test_df


def prepare_dataloaders(
    df: pd.DataFrame,
    transformer: Optional[PersonalBaselineTransformer] = None,
    batch_size: int = 32,
    train_ratio: float = 0.70,
    val_ratio: float = 0.15,
    seed: int = 42,
) -> Dict[str, Any]:
    """Prepare zero-leakage DataLoaders with personal 14-day baseline normalization.

    Returns:
        Dict containing train_loader, val_loader, test_loader, class_weights, and metadata.
    """
    if transformer is None:
        transformer = PersonalBaselineTransformer()

    # 1. Split strictly by employee
    train_df, val_df, test_df = split_employees(
        df, train_ratio=train_ratio, val_ratio=val_ratio, seed=seed
    )

    # 2. Extract sequences with personal 14-day baseline
    X_train, y_train_class, y_train_risk, meta_train = transformer.extract_sequences(train_df)
    X_val, y_val_class, y_val_risk, meta_val = transformer.extract_sequences(val_df)
    X_test, y_test_class, y_test_risk, meta_test = transformer.extract_sequences(test_df)

    # 3. Calculate class weights on train set for balanced CrossEntropy
    class_counts = np.bincount(y_train_class, minlength=4)
    total_samples = len(y_train_class)
    class_weights = total_samples / (4.0 * np.maximum(class_counts, 1.0))
    class_weights_tensor = torch.tensor(class_weights, dtype=torch.float32)

    # 4. Wrap in Datasets and DataLoaders
    train_dataset = WorkSenseDataset(X_train, y_train_class, y_train_risk, meta_train)
    val_dataset = WorkSenseDataset(X_val, y_val_class, y_val_risk, meta_val)
    test_dataset = WorkSenseDataset(X_test, y_test_class, y_test_risk, meta_test)

    train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True)
    val_loader = DataLoader(val_dataset, batch_size=batch_size, shuffle=False)
    test_loader = DataLoader(test_dataset, batch_size=batch_size, shuffle=False)

    return {
        "train_loader": train_loader,
        "val_loader": val_loader,
        "test_loader": test_loader,
        "train_dataset": train_dataset,
        "val_dataset": val_dataset,
        "test_dataset": test_dataset,
        "class_weights": class_weights_tensor,
        "transformer": transformer,
        "split_counts": {
            "train_employees": int(train_df["employee_id"].nunique()),
            "val_employees": int(val_df["employee_id"].nunique()),
            "test_employees": int(test_df["employee_id"].nunique()),
            "train_samples": len(X_train),
            "val_samples": len(X_val),
            "test_samples": len(X_test),
        },
    }
