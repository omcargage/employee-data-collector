"""Utility script to initialize and inspect tables in an SQLite database file.

Verifies schema versioning, table creation, and column indexes.
"""
from pathlib import Path
import sqlite3
import sys

# Add agent and shared to path
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root / "agent"))
sys.path.insert(0, str(repo_root / "shared"))

from edc_agent.storage.database import Database


def main():
    db_path = repo_root / "agent" / "edc_local.db"
    print(f"Initializing database at: {db_path}")

    # Initialize Database (runs migrations if not already applied)
    db = Database(db_path)
    db.close()

    # Open standard sqlite3 connection and inspect
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT MAX(version), applied_at FROM schema_version;")
    ver, applied_at = cursor.fetchone()
    print(f"Current Schema Version: {ver} (applied: {applied_at})")

    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name;"
    )
    tables = [row["name"] for row in cursor.fetchall()]
    print(f"Tables found ({len(tables)}):")
    for t in tables:
        cursor.execute(f"PRAGMA table_info({t});")
        cols = [c[1] for c in cursor.fetchall()]
        print(f"  - {t}: {', '.join(cols)}")

    conn.close()


if __name__ == "__main__":
    main()
