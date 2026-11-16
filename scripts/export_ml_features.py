"""Export machine-learning ready datasets with per-person rolling baseline normalization and subject splits.

Usage:
    python scripts/export_ml_features.py [--db PATH] [--output-dir PATH] [--test-size 0.2] [--window-size 7]
"""
import argparse
from pathlib import Path
import sys

from edc_agent.ml import export_ml_dataset, prepare_ml_records_from_database
from edc_agent.storage.database import Database


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export ML-ready features with per-person rolling median/MAD normalization and subject splits"
    )
    parser.add_argument(
        "--db",
        default=str(Path.home() / ".edc" / "agent.db"),
        help="Path to SQLite database file (default: ~/.edc/agent.db)",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        default=".",
        help="Directory to save output ML dataset CSV (default: current directory)",
    )
    parser.add_argument(
        "--prefix",
        default="edc_ml_dataset",
        help="Prefix for output CSV filename",
    )
    parser.add_argument(
        "--window-size",
        type=int,
        default=7,
        help="Sliding lookback window for rolling median and MAD (default: 7)",
    )
    parser.add_argument(
        "--test-size",
        type=float,
        default=0.2,
        help="Fraction of unique persons assigned to test split (default: 0.2)",
    )
    parser.add_argument(
        "--person-col",
        default="person_id",
        help="Column identifying individual employees/subjects (default: person_id)",
    )
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        sys.stderr.write(f"[EDC ERROR] Database not found at: {db_path}\n")
        return 1

    sys.stdout.write("======================================================================\n")
    sys.stdout.write("  EDC Machine Learning Feature Exporter\n")
    sys.stdout.write("======================================================================\n")
    sys.stdout.write(f"Database:     {db_path.resolve()}\n")
    sys.stdout.write(f"Window Size:  {args.window_size} observations\n")
    sys.stdout.write(f"Test Ratio:   {args.test_size * 100:.0f}% subjects\n\n")

    db = Database(db_path)
    records = prepare_ml_records_from_database(db=db)

    if not records:
        sys.stdout.write("[EDC WARNING] No 15-minute rollups found in database. Exiting.\n")
        return 0

    out_file = Path(args.output_dir) / f"{args.prefix}.csv"
    file_path, stats = export_ml_dataset(
        records=records,
        output_csv_path=out_file,
        person_col=args.person_col,
        window_size=args.window_size,
        test_size=args.test_size,
    )

    sys.stdout.write(f"[SUCCESS] Exported ML dataset to: {file_path.resolve()}\n")
    sys.stdout.write(f"  Total records:      {stats.get('total_records', 0)}\n")
    sys.stdout.write(f"  Train records:      {stats.get('train_records', 0)}\n")
    sys.stdout.write(f"  Test records:       {stats.get('test_records', 0)}\n")
    sys.stdout.write(f"  Unique subjects:    {stats.get('n_persons', 0)} "
                     f"(Train: {stats.get('train_persons_count', 0)}, Test: {stats.get('test_persons_count', 0)})\n")
    sys.stdout.write(f"  Total feature cols: {stats.get('features_count', 0)}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
