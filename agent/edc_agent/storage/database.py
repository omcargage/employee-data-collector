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

    def get_rollup_daily_by_id(self, rollup_id: int) -> Optional[RollupDaily]:
        """Fetch and reconstruct a validated RollupDaily instance by id."""
        conn = self.get_connection()
        cursor = conn.execute(
            "SELECT payload FROM rollups_daily WHERE id = ?;", (rollup_id,)
        )
        row = cursor.fetchone()
        if not row:
            return None
        return RollupDaily.model_validate_json(row["payload"])

    def check_rollup_15min_exists(self, window_start: str, window_end: str) -> bool:
        """Check if a 15-minute rollup already exists for given bounds."""
        conn = self.get_connection()
        cur = conn.execute(
            "SELECT 1 FROM rollups_15min WHERE window_start = ? AND window_end = ? LIMIT 1;",
            (window_start, window_end),
        )
        return cur.fetchone() is not None

    def get_rollups_15min_count(self) -> int:
        """Return total count of 15-minute rollups stored."""
        conn = self.get_connection()
        cur = conn.execute("SELECT COUNT(*) FROM rollups_15min;")
        row = cur.fetchone()
        return row[0] if row else 0

    def get_rollups_daily_count(self) -> int:
        """Return total count of daily rollups stored."""
        conn = self.get_connection()
        cur = conn.execute("SELECT COUNT(*) FROM rollups_daily;")
        row = cur.fetchone()
        return row[0] if row else 0

    def get_recent_rollups_daily(self, limit: int = 7) -> List[RollupDaily]:
        """Fetch up to `limit` recent RollupDaily objects ordered by logical_day descending."""
        conn = self.get_connection()
        cur = conn.execute(
            "SELECT payload FROM rollups_daily ORDER BY logical_day DESC LIMIT ?;",
            (limit,),
        )
        return [RollupDaily.model_validate_json(row["payload"]) for row in cur.fetchall()]

    def get_agent_state(self, key: str) -> Optional[str]:
        """Fetch a value from the agent_state key-value store."""
        conn = self.get_connection()
        cur = conn.execute("SELECT value FROM agent_state WHERE key = ?;", (key,))
        row = cur.fetchone()
        return row["value"] if row else None

    def set_agent_state(self, key: str, value: str) -> None:
        """Store or update a key-value pair in agent_state."""
        conn = self.get_connection()
        query = """
        INSERT OR REPLACE INTO agent_state (key, value, updated_at)
        VALUES (?, ?, datetime('now', 'utc'));
        """
        if self._is_memory:
            conn.execute(query, (key, value))
            conn.commit()
        else:
            with conn:
                conn.execute(query, (key, value))

    def insert_consent_record(self, consented_at: str, version: str, status: str = "consented") -> int:
        """Record a user privacy consent decision in consent_records."""
        conn = self.get_connection()
        query = "INSERT INTO consent_records (consented_at, version, status) VALUES (?, ?, ?);"
        if self._is_memory:
            cur = conn.execute(query, (consented_at, version, status))
            conn.commit()
            return cur.lastrowid  # type: ignore[return-value]
        with conn:
            cur = conn.execute(query, (consented_at, version, status))
            return cur.lastrowid  # type: ignore[return-value]

    def get_latest_consent_record(self) -> Optional[sqlite3.Row]:
        """Fetch the most recent consent decision."""
        conn = self.get_connection()
        cur = conn.execute("SELECT * FROM consent_records ORDER BY id DESC LIMIT 1;")
        return cur.fetchone()

    def insert_self_report(self, ts_utc: str, label: str, value: str) -> int:
        """Store a self-report label or metric in self_reports."""
        conn = self.get_connection()
        query = "INSERT INTO self_reports (ts_utc, label, value) VALUES (?, ?, ?);"
        if self._is_memory:
            cur = conn.execute(query, (ts_utc, label, value))
            conn.commit()
            return cur.lastrowid  # type: ignore[return-value]
        with conn:
            cur = conn.execute(query, (ts_utc, label, value))
            return cur.lastrowid  # type: ignore[return-value]

    def get_self_reports(self) -> List[sqlite3.Row]:
        """Fetch all recorded self-reports."""
        conn = self.get_connection()
        cur = conn.execute("SELECT * FROM self_reports ORDER BY id ASC;")
        return cur.fetchall()

    def get_all_rollups_15min(self) -> List[Rollup15Min]:
        """Fetch all 15-minute rollups ordered by window_start."""
        conn = self.get_connection()
        cur = conn.execute("SELECT payload FROM rollups_15min ORDER BY window_start ASC;")
        return [Rollup15Min.model_validate_json(row["payload"]) for row in cur.fetchall()]

    def get_all_rollups_daily(self) -> List[RollupDaily]:
        """Fetch all daily rollups ordered by logical_day."""
        conn = self.get_connection()
        cur = conn.execute("SELECT payload FROM rollups_daily ORDER BY logical_day ASC;")
        return [RollupDaily.model_validate_json(row["payload"]) for row in cur.fetchall()]

    def insert_gap_log(
        self,
        start_ts: Union[str, datetime],
        end_ts: Union[str, datetime],
        duration_s: float,
        gap_type: str,
    ) -> int:
        """Record an idle, away, or unknown gap interval in gap_log."""
        s_iso = start_ts.isoformat() if isinstance(start_ts, datetime) else str(start_ts)
        e_iso = end_ts.isoformat() if isinstance(end_ts, datetime) else str(end_ts)
        conn = self.get_connection()
        query = """
        INSERT INTO gap_log (start_ts, end_ts, duration_s, gap_type)
        VALUES (?, ?, ?, ?);
        """
        params = (s_iso, e_iso, float(duration_s), gap_type)
        if self._is_memory:
            cur = conn.execute(query, params)
            conn.commit()
            return cur.lastrowid  # type: ignore[return-value]
        with conn:
            cur = conn.execute(query, params)
            return cur.lastrowid  # type: ignore[return-value]

    def get_gap_logs(self, gap_type: Optional[str] = None) -> List[sqlite3.Row]:
        """Fetch all logged gaps, optionally filtered by gap_type."""
        conn = self.get_connection()
        if gap_type:
            cur = conn.execute(
                "SELECT * FROM gap_log WHERE gap_type = ? ORDER BY start_ts ASC;",
                (gap_type,),
            )
        else:
            cur = conn.execute("SELECT * FROM gap_log ORDER BY start_ts ASC;")
        return cur.fetchall()

    def count_gap_logs(self, gap_type: Optional[str] = None) -> int:
        """Return total count of gaps logged, optionally filtered by gap_type."""
        conn = self.get_connection()
        if gap_type:
            cur = conn.execute(
                "SELECT COUNT(*) FROM gap_log WHERE gap_type = ?;",
                (gap_type,),
            )
        else:
            cur = conn.execute("SELECT COUNT(*) FROM gap_log;")
        row = cur.fetchone()
        return row[0] if row else 0

    def get_dropped_events_count(self) -> int:
        """Fetch cumulative dropped events count from agent_state."""
        val = self.get_agent_state("dropped_events_count")
        return int(val) if val is not None else 0

    def set_dropped_events_count(self, count: int) -> None:
        """Persist cumulative dropped events count to agent_state."""
        self.set_agent_state("dropped_events_count", str(count))

    def clear_all_data(self) -> None:
        """Wipe all user data tables and state (delete-all-data)."""
        tables = [
            "rollups_15min",
            "rollups_daily",
            "upload_queue",
            "self_reports",
            "consent_records",
            "agent_state",
            "gap_log",
        ]
        conn = self.get_connection()
        if self._is_memory:
            for t in tables:
                conn.execute(f"DELETE FROM {t};")
            conn.commit()
        else:
            with conn:
                for t in tables:
                    conn.execute(f"DELETE FROM {t};")
            conn.execute("VACUUM;")

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
