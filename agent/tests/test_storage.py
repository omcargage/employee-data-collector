"""Tests for EDC SQLite database, schema migrations, and upload queue operations."""
from datetime import date, datetime, timezone
from pathlib import Path
import sqlite3
from uuid import uuid4
import pytest

from edc_agent.storage.database import Database
from edc_agent.storage.queue import UploadQueue
from edc_schemas import Rollup15Min, RollupDaily, WindowBlocks


def test_in_memory_database_tables():
    """Verify that in-memory SQLite initializes schema_version and creates all required tables."""
    db = Database(":memory:")
    tables = db.list_tables()

    expected_tables = {
        "schema_version",
        "rollups_15min",
        "rollups_daily",
        "upload_queue",
        "self_reports",
        "consent_records",
        "agent_state",
        "gap_log",
    }
    assert expected_tables.issubset(set(tables)), f"Missing tables: {expected_tables - set(tables)}"

    # Check migration version
    conn = db.get_connection()
    cursor = conn.execute("SELECT MAX(version) FROM schema_version;")
    assert cursor.fetchone()[0] == 1


def test_insert_and_get_rollup_15min():
    """Verify storing and fetching a validated 15-minute rollup with indexed bounds."""
    db = Database(":memory:")
    now = datetime.now(timezone.utc)
    blocks = WindowBlocks(n_char=50, n_backspace=2, flight_time_n=48, covered_s=900.0)

    rollup = Rollup15Min(
        window_start=now,
        window_end=now,
        coverage_ratio=1.0,
        low_coverage=False,
        total_keystrokes=52,
        char_keystrokes=50,
        backspace_count=2,
        blocks=blocks,
    )

    row_id = db.insert_rollup_15min(rollup)
    assert row_id >= 1

    fetched = db.get_rollup_15min(row_id)
    assert fetched is not None
    assert fetched.total_keystrokes == 52
    assert fetched.blocks.n_char == 50
    assert fetched.coverage_ratio == 1.0


def test_insert_and_get_rollup_daily():
    """Verify storing and fetching a validated daily rollup."""
    db = Database(":memory:")
    daily = RollupDaily(
        logical_day=date(2026, 11, 15),
        coverage_ratio=0.95,
        low_coverage=False,
        avg_session_duration_mins=42.0,
        total_breaks_count=5,
    )

    row_id = db.insert_rollup_daily(daily)
    assert row_id >= 1

    fetched = db.get_rollup_daily("2026-11-15")
    assert fetched is not None
    assert fetched.logical_day == date(2026, 11, 15)
    assert fetched.avg_session_duration_mins == 42.0
    assert fetched.total_breaks_count == 5


def test_upload_queue_lifecycle():
    """Verify enqueueing items, fetching pending batches, and marking done/failed."""
    db = Database(":memory:")
    queue = UploadQueue(db)
    batch_id = uuid4()

    q_id1 = queue.enqueue("15min", 1, batch_id=batch_id)
    q_id2 = queue.enqueue("daily", 1, batch_id=batch_id)
    assert q_id1 == 1
    assert q_id2 == 2

    # Fetch pending
    pending = queue.fetch_pending(limit=10)
    assert len(pending) == 2
    assert pending[0].status == "pending"
    assert pending[0].rollup_type == "15min"
    assert pending[1].rollup_type == "daily"

    # Mark uploading
    queue.mark_uploading([q_id1])
    conn = db.get_connection()
    row = conn.execute("SELECT status, attempts, last_attempt_at FROM upload_queue WHERE id = ?;", (q_id1,)).fetchone()
    assert row["status"] == "uploading"
    assert row["attempts"] == 1
    assert row["last_attempt_at"] is not None

    # Mark done
    queue.mark_done([q_id1, q_id2])
    pending_after = queue.fetch_pending(limit=10)
    assert len(pending_after) == 0

    # Verify both are marked done
    rows = conn.execute("SELECT status FROM upload_queue;").fetchall()
    assert all(r["status"] == "done" for r in rows)


def test_open_file_db_and_inspect_tables(tmp_path: Path):
    """Verify opening a real file-based .db file and inspecting its tables directly."""
    db_file = tmp_path / "edc_test.db"
    assert not db_file.exists()

    # Initialize file database and run migrations
    db = Database(db_file)
    assert db_file.exists()

    # Close and reopen using standard sqlite3 to directly inspect .db file
    db.close()
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name;"
    )
    table_names = [row["name"] for row in cursor.fetchall()]
    conn.close()

    expected_tables = [
        "agent_state",
        "consent_records",
        "gap_log",
        "rollups_15min",
        "rollups_daily",
        "schema_version",
        "self_reports",
        "upload_queue",
    ]
    assert table_names == expected_tables, f"Tables in .db file did not match: {table_names}"
