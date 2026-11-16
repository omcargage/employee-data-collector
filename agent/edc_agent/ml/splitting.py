"""Person-grouped dataset splitting helpers for machine learning validation.

Guarantees 100% subject isolation (Leave-One-Subject-Out / GroupKFold):
Observations belonging to the same employee never appear in both train and test splits,
preventing subject identity leakage and unrealistic optimistic evaluation metrics.
"""
from collections import defaultdict
import random
from typing import Any, Dict, Iterator, List, Tuple


def split_by_person(
    records: List[Dict[str, Any]],
    person_col: str = "person_id",
    test_size: float = 0.2,
    seed: int = 42,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Partition records into train and test sets strictly by individual person/employee.

    Args:
        records: List of dictionary records.
        person_col: Field containing the subject or employee identifier.
        test_size: Approximate fraction of unique persons assigned to the test set (0.0 to 1.0).
        seed: Random seed for deterministic reproducibility.

    Returns:
        Tuple of (train_records, test_records) with 'split' field set.
    """
    if not records:
        return [], []

    # 1. Identify all distinct persons
    unique_persons = sorted(list({str(r.get(person_col, "default")) for r in records}))
    n_persons = len(unique_persons)

    if n_persons <= 1:
        # Cannot split single person without leakage; assign all to train
        for r in records:
            r["split"] = "train"
        return list(records), []

    rng = random.Random(seed)
    shuffled_persons = list(unique_persons)
    rng.shuffle(shuffled_persons)

    n_test = max(1, int(round(n_persons * test_size)))
    test_persons = set(shuffled_persons[:n_test])
    train_persons = set(shuffled_persons[n_test:])

    train_records: List[Dict[str, Any]] = []
    test_records: List[Dict[str, Any]] = []

    for r in records:
        row = dict(r)
        pid = str(row.get(person_col, "default"))
        if pid in test_persons:
            row["split"] = "test"
            test_records.append(row)
        else:
            row["split"] = "train"
            train_records.append(row)

    # Verification: assert 0% subject overlap
    train_pids = {r.get(person_col) for r in train_records}
    test_pids = {r.get(person_col) for r in test_records}
    assert train_pids.isdisjoint(test_pids), "Subject leakage detected between train and test splits!"

    return train_records, test_records


def group_kfold_by_person(
    records: List[Dict[str, Any]],
    person_col: str = "person_id",
    n_splits: int = 5,
    seed: int = 42,
) -> Iterator[Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]]:
    """Generate K-Fold cross validation splits partitioned by person.

    Yields:
        (train_records, val_records) for each fold with 'fold' and 'split' set.
    """
    if not records:
        return

    unique_persons = sorted(list({str(r.get(person_col, "default")) for r in records}))
    n_persons = len(unique_persons)

    if n_persons < 2:
        raise ValueError(f"group_kfold_by_person requires at least 2 distinct persons, found {n_persons}")

    actual_splits = min(n_splits, n_persons)
    rng = random.Random(seed)
    shuffled_persons = list(unique_persons)
    rng.shuffle(shuffled_persons)

    # Divide persons into K folds
    person_folds: List[set] = [set() for _ in range(actual_splits)]
    for i, pid in enumerate(shuffled_persons):
        person_folds[i % actual_splits].add(pid)

    for fold_idx in range(actual_splits):
        val_persons = person_folds[fold_idx]
        train_fold: List[Dict[str, Any]] = []
        val_fold: List[Dict[str, Any]] = []

        for r in records:
            row = dict(r)
            row["fold"] = fold_idx
            pid = str(row.get(person_col, "default"))
            if pid in val_persons:
                row["split"] = "val"
                val_fold.append(row)
            else:
                row["split"] = "train"
                train_fold.append(row)

        yield train_fold, val_fold
