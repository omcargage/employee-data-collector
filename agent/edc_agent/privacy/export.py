"""Feature export utility joining 15-minute and daily rollups with self-report labels.

Generates CSV files containing strictly columns declared in docs/metrics_registry.yaml plus
the self-report labels (stress, energy, workload).
"""
from datetime import datetime, timezone
from pathlib import Path
import csv
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from edc_schemas import Rollup15Min, RollupDaily
from edc_agent.privacy.self_report import get_all_checkins_by_day
from edc_agent.storage.database import Database
from edc_agent.timeutil import to_logical_day


def load_registry_columns(registry_path: Optional[Union[str, Path]] = None) -> Tuple[List[str], List[str]]:
    """Parse metrics_registry.yaml and extract ordered lists of 15min and daily metric names."""
    if registry_path is not None:
        p = Path(registry_path)
    else:
        # Default relative to this file: agent/edc_agent/privacy/export.py -> ../../../docs/metrics_registry.yaml
        p = Path(__file__).resolve().parent.parent.parent.parent / "docs" / "metrics_registry.yaml"

    if not p.exists():
        # Fallback to local employee-data-collector/docs/metrics_registry.yaml
        alt_p = Path("docs/metrics_registry.yaml").resolve()
        if alt_p.exists():
            p = alt_p
        else:
            alt_p2 = Path("../docs/metrics_registry.yaml").resolve()
            if alt_p2.exists():
                p = alt_p2

    cols_15min: List[str] = []
    cols_daily: List[str] = []

    if p.exists():
        current_name: Optional[str] = None
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped.startswith("- name:"):
                    current_name = stripped.split(":", 1)[1].strip()
                elif stripped.startswith("window:") and current_name:
                    win = stripped.split(":", 1)[1].strip()
                    if win == "15min":
                        cols_15min.append(current_name)
                    elif win == "daily":
                        cols_daily.append(current_name)
                    current_name = None

    return cols_15min, cols_daily


LABEL_COLUMNS = ["stress", "energy", "workload"]


def export_data_to_csv(
    db: Database,
    output_dir: Union[str, Path] = Path("."),
    prefix: str = "edc_export",
    registry_path: Optional[Union[str, Path]] = None,
    tz_name: str = "Asia/Kolkata",
) -> Tuple[Path, Path]:
    """Export 15-minute and daily rollups joined with self-report labels to CSV.

    Guarantees no unexpected columns: output CSV headers contain strictly columns declared
    in the metrics registry plus joined labels (stress, energy, workload).
    """
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    cols_15min, cols_daily = load_registry_columns(registry_path)

    # 1. Fetch data
    rollups_15min = db.get_all_rollups_15min()
    rollups_daily = db.get_all_rollups_daily()
    labels_by_day = get_all_checkins_by_day(db)

    # Output headers: strictly registry columns + label columns
    headers_15min = list(cols_15min) + list(LABEL_COLUMNS)
    headers_daily = list(cols_daily) + list(LABEL_COLUMNS)

    file_15min = out_path / f"{prefix}_15min.csv"
    file_daily = out_path / f"{prefix}_daily.csv"

    # 2. Write 15-minute rollups CSV
    with open(file_15min, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers_15min, extrasaction="ignore")
        writer.writeheader()

        for r in rollups_15min:
            row_dict = r.model_dump()

            # Map timestamp alias if present in registry
            if "timestamp" in cols_15min and "timestamp" not in row_dict:
                row_dict["timestamp"] = r.window_start.isoformat()

            # Join daily label
            log_day = to_logical_day(r.window_start, tz=tz_name)
            day_str = log_day.isoformat()
            lbl = labels_by_day.get(day_str, {})
            row_dict["stress"] = lbl.get("stress", "")
            row_dict["energy"] = lbl.get("energy", "")
            row_dict["workload"] = lbl.get("workload", "")

            # Filter to strictly allow only declared headers
            filtered_row = {col: row_dict.get(col, "") for col in headers_15min}
            writer.writerow(filtered_row)

    # 3. Write Daily rollups CSV
    with open(file_daily, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers_daily, extrasaction="ignore")
        writer.writeheader()

        for d in rollups_daily:
            row_dict = d.model_dump()

            day_str = d.logical_day.isoformat()
            if "day" in cols_daily and not row_dict.get("day"):
                row_dict["day"] = day_str

            lbl = labels_by_day.get(day_str, {})
            row_dict["stress"] = lbl.get("stress", "")
            row_dict["energy"] = lbl.get("energy", "")
            row_dict["workload"] = lbl.get("workload", "")

            filtered_row = {col: row_dict.get(col, "") for col in headers_daily}
            writer.writerow(filtered_row)

    return file_15min, file_daily
