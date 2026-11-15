"""SQLite storage management and migration runner for local EDC data.

Manages schema versioning, indexed rollups stored as validated JSON, queue state, and audit logs.
"""
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional, Union

from edc_schemas import Rollup15Min, RollupDaily


MIGRATION_V1 = """
-- 1. Schema version tracking
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

-- 2. 15-Minute rollups table
CREATE TABLE IF NOT EXISTS rollups_15min (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    coverage_ratio REAL NOT NULL,
    low_coverage INTEGER NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'utc'))
);
CREATE INDEX IF NOT EXISTS idx_rollups_15min_window_start ON rollups_15min(window_start);
CREATE INDEX IF NOT EXISTS idx_rollups_15min_window_end ON rollups_15min(window_end);

-- 3. Daily rollups table
CREATE TABLE IF NOT EXISTS rollups_daily (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    logical_day TEXT NOT NULL UNIQUE,
    coverage_ratio REAL NOT NULL,
    low_coverage INTEGER NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'utc'))
);
CREATE INDEX IF NOT EXISTS idx_rollups_daily_logical_day ON rollups_daily(logical_day);

-- 4. Upload queue table
CREATE TABLE IF NOT EXISTS upload_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id TEXT NOT NULL,
    rollup_type TEXT NOT NULL,
    rollup_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    last_attempt_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'utc'))
);
CREATE INDEX IF NOT EXISTS idx_upload_queue_status ON upload_queue(status);

-- 5. Self-reports table
CREATE TABLE IF NOT EXISTS self_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc TEXT NOT NULL,
    label TEXT NOT NULL,
    value TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'utc'))
);
CREATE INDEX IF NOT EXISTS idx_self_reports_ts ON self_reports(ts_utc);

-- 6. Consent records table
CREATE TABLE IF NOT EXISTS consent_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    consented_at TEXT NOT NULL,
    version TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'utc'))
);

-- 7. Agent state table (key-value store for checkpoints)
CREATE TABLE IF NOT EXISTS agent_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'utc'))
);

-- 8. Gap log table
CREATE TABLE IF NOT EXISTS gap_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    start_ts TEXT NOT NULL,
    end_ts TEXT NOT NULL,
    duration_s REAL NOT NULL,
    gap_type TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'utc'))
);
CREATE INDEX IF NOT EXISTS idx_gap_log_start ON gap_log(start_ts);
"""

MIGRATIONS: Dict[int, str] = {
    1: MIGRATION_V1,
}


class Database:
    """SQLite database manager for the EDC desktop agent."""

    def __init__(self, db_path: Union[str, Path] = ":memory:"):
        self.db_path = str(db_path)
        self._is_memory = self.db_path == ":memory:"
        self._memory_conn: Optional[sqlite3.Connection] = None

        if self._is_memory:
            # Keep a persistent connection for in-memory databases (thread-safe for testing)
            self._memory_conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._memory_conn.row_factory = sqlite3.Row
            self._configure_connection(self._memory_conn)
            self.run_migrations(self._memory_conn)
        else:
            path_obj = Path(self.db_path)
            path_obj.parent.mkdir(parents=True, exist_ok=True)
            with self.get_connection() as conn:
                self.run_migrations(conn)

    def _configure_connection(self, conn: sqlite3.Connection) -> None:
        conn.execute("PRAGMA foreign_keys = ON;")
        if not self._is_memory:
            conn.execute("PRAGMA journal_mode = WAL;")

    def get_connection(self) -> sqlite3.Connection:
        """Return a configured SQLite connection."""
        if self._is_memory:
            return self._memory_conn  # type: ignore[return-value]
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        self._configure_connection(conn)
        return conn

    @staticmethod
    def run_migrations(conn: sqlite3.Connection) -> int:
        """Run all pending SQL migrations in sequence, recording versions in schema_version."""
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                );
                """
            )
            cursor = conn.execute("SELECT MAX(version) FROM schema_version;")
            row = cursor.fetchone()
            current_version = row[0] if (row and row[0] is not None) else 0

            for ver in sorted(MIGRATIONS.keys()):
                if ver > current_version:
                    sql_script = MIGRATIONS[ver]
                    conn.executescript(sql_script)
                    now_utc = datetime.now(timezone.utc).isoformat()
                    conn.execute(
                        "INSERT INTO schema_version (version, applied_at) VALUES (?, ?);",
                        (ver, now_utc),
                    )
                    current_version = ver

        return current_version

    def insert_rollup_15min(self, rollup: Union[Rollup15Min, dict]) -> int:
        """Validate and insert a 15-minute rollup JSON payload with indexed bounds."""
        if isinstance(rollup, dict):
            validated = Rollup15Min(**rollup)
        else:
            validated = rollup

        conn = self.get_connection()
        query = """
        INSERT INTO rollups_15min (
            window_start, window_end, coverage_ratio, low_coverage, payload
        ) VALUES (?, ?, ?, ?, ?);
        """
        params = (
            validated.window_start.isoformat(),
            validated.window_end.isoformat(),
            float(validated.coverage_ratio),
            1 if validated.low_coverage else 0,
            validated.model_dump_json(),
        )
        if self._is_memory:
            cur = conn.execute(query, params)
            conn.commit()
            return cur.lastrowid  # type: ignore[return-value]

        with conn:
            cur = conn.execute(query, params)
            return cur.lastrowid  # type: ignore[return-value]

    def get_rollup_15min(self, rollup_id: int) -> Optional[Rollup15Min]:
        """Fetch and reconstruct a validated Rollup15Min instance by id."""
        conn = self.get_connection()
        cursor = conn.execute(
            "SELECT payload FROM rollups_15min WHERE id = ?;", (rollup_id,)
        )
        row = cursor.fetchone()
        if not row:
            return None
        return Rollup15Min.model_validate_json(row["payload"])

    def insert_rollup_daily(self, rollup: Union[RollupDaily, dict]) -> int:
        """Validate and insert a daily rollup JSON payload with unique logical_day."""
        if isinstance(rollup, dict):
            validated = RollupDaily(**rollup)
        else:
            validated = rollup

        conn = self.get_connection()
        query = """
        INSERT INTO rollups_daily (
            logical_day, coverage_ratio, low_coverage, payload
        ) VALUES (?, ?, ?, ?);
        """
        params = (
            validated.logical_day.isoformat(),
            float(validated.coverage_ratio),
            1 if validated.low_coverage else 0,
            validated.model_dump_json(),
        )
        if self._is_memory:
            cur = conn.execute(query, params)
            conn.commit()
            return cur.lastrowid  # type: ignore[return-value]

        with conn:
            cur = conn.execute(query, params)
            return cur.lastrowid  # type: ignore[return-value]

    def get_rollup_daily(self, logical_day: str) -> Optional[RollupDaily]:
        """Fetch and reconstruct a validated RollupDaily instance by logical_day."""
        conn = self.get_connection()
        cursor = conn.execute(
            "SELECT payload FROM rollups_daily WHERE logical_day = ?;", (logical_day,)
        )
        row = cursor.fetchone()
        if not row:
            return None
        return RollupDaily.model_validate_json(row["payload"])

    def list_tables(self) -> List[str]:
        """Return all user table names created in the database."""
        conn = self.get_connection()
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name;"
        )
        return [row["name"] for row in cursor.fetchall()]

    def close(self) -> None:
        """Close connection if open."""
        if self._memory_conn:
            self._memory_conn.close()
            self._memory_conn = None
