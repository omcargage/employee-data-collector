"""Dataset exporter for ML pipelines joining features, rolling baselines, and self-report labels."""
import csv
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from edc_agent.ml.normalisation import normalize_features_per_person
from edc_agent.ml.splitting import split_by_person
from edc_agent.privacy.self_report import get_all_checkins_by_day
from edc_agent.storage.database import Database
from edc_agent.timeutil import to_logical_day


def prepare_ml_records_from_database(
    db: Database,
    person_id: Optional[str] = None,
    tz_name: str = "Asia/Kolkata",
) -> List[Dict[str, Any]]:
    """Assemble flat dataset records from agent SQLite database joining 15-min rollups and check-ins."""
    pid = person_id or db.get_agent_state("employee_code") or db.get_agent_state("device_id") or "emp-1"
    rollups = db.get_all_rollups_15min()
    labels_by_day = get_all_checkins_by_day(db)

    records: List[Dict[str, Any]] = []

    for r in rollups:
        row = r.model_dump()
        row["person_id"] = pid
        row["timestamp"] = r.window_start.isoformat()

        # Join daily check-in ratings
        log_day = to_logical_day(r.window_start, tz=tz_name)
        day_str = log_day.isoformat()
        lbl = labels_by_day.get(day_str, {})
        row["stress"] = lbl.get("stress", None)
        row["energy"] = lbl.get("energy", None)
        row["workload"] = lbl.get("workload", None)

        # Flatten nested blocks building blocks into top-level numerical features if needed
        blocks = row.pop("blocks", {})
        if isinstance(blocks, dict):
            for bk, bv in blocks.items():
                if isinstance(bv, (int, float)) and not isinstance(bv, bool):
                    row[f"block_{bk}"] = bv

        records.append(row)

    return records


def export_ml_dataset(
    records: List[Dict[str, Any]],
    output_csv_path: Union[str, Path],
    person_col: str = "person_id",
    feature_cols: Optional[List[str]] = None,
    sort_col: str = "timestamp",
    window_size: int = 7,
    test_size: float = 0.2,
    seed: int = 42,
) -> Tuple[Path, Dict[str, Any]]:
    """Generate per-person-normalised ML dataset with train/test subject splits and write to CSV.

    Args:
        records: Raw records containing telemetry features, person identifier, and labels.
        output_csv_path: Target path for the output CSV file.
        person_col: Person identifier column.
        feature_cols: Numerical features to normalize.
        sort_col: Column for chronological ordering per subject.
        window_size: Rolling lookback window size for median/MAD.
        test_size: Ratio of subjects allocated to test split.
        seed: Split reproducibility seed.

    Returns:
        Tuple of (output_file_path, metadata_dict).
    """
    out_file = Path(output_csv_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)

    if not records:
        out_file.write_text("", encoding="utf-8")
        return out_file, {"total_records": 0, "n_persons": 0}

    # 1. Apply per-person rolling median/MAD normalization
    normalized_records = normalize_features_per_person(
        records=records,
        person_col=person_col,
        feature_cols=feature_cols,
        sort_col=sort_col,
        window_size=window_size,
    )

    # 2. Partition by subject into train and test
    train_records, test_records = split_by_person(
        records=normalized_records,
        person_col=person_col,
        test_size=test_size,
        seed=seed,
    )

    combined_dataset = train_records + test_records
    combined_dataset.sort(key=lambda r: str(r.get(sort_col, "")))

    # 3. Determine fieldnames
    all_fieldnames: List[str] = []
    seen = set()
    for row in combined_dataset:
        for k in row.keys():
            if k not in seen:
                seen.add(k)
                all_fieldnames.append(k)

    # Put person_id, timestamp, labels, and split first
    priority_order = [person_col, sort_col, "stress", "energy", "workload", "split"]
    ordered_fields = [f for f in priority_order if f in seen]
    ordered_fields += [f for f in all_fieldnames if f not in ordered_fields]

    # 4. Write CSV
    with open(out_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=ordered_fields, extrasaction="ignore")
        writer.writeheader()
        for row in combined_dataset:
            writer.writerow(row)

    unique_persons = {r.get(person_col) for r in combined_dataset}
    train_persons = {r.get(person_col) for r in train_records}
    test_persons = {r.get(person_col) for r in test_records}

    summary = {
        "output_file": str(out_file.resolve()),
        "total_records": len(combined_dataset),
        "train_records": len(train_records),
        "test_records": len(test_records),
        "n_persons": len(unique_persons),
        "train_persons_count": len(train_persons),
        "test_persons_count": len(test_persons),
        "features_count": len(ordered_fields),
    }

    return out_file, summary
