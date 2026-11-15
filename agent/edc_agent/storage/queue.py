"""Upload queue manager for outbound metric rollups.

Enqueues local 15-minute and daily rollups, fetches pending batches, and marks delivery status.
"""
from datetime import datetime, timezone
from typing import List, Optional, Union
from uuid import UUID, uuid4
from pydantic import BaseModel, ConfigDict, Field

from .database import Database


class QueueItem(BaseModel):
    """Represents a scheduled rollup item in the upload queue."""
    model_config = ConfigDict(extra="forbid")

    id: int = Field(description="Unique queue row id")
    batch_id: UUID = Field(description="Batch identifier UUID")
    rollup_type: str = Field(description="Type of rollup: '15min' or 'daily'")
    rollup_id: int = Field(description="Foreign key id in rollups_15min or rollups_daily")
    status: str = Field(default="pending", description="Delivery status: pending, uploading, done, failed")
    attempts: int = Field(default=0, description="Count of attempted delivery transmissions")
    last_attempt_at: Optional[str] = Field(default=None, description="Timestamp of most recent attempt")
    created_at: Optional[str] = Field(default=None, description="Enqueue timestamp")


class UploadQueue:
    """Manages the lifecycle of items in the upload_queue table."""

    def __init__(self, db: Database):
        self.db = db

    def enqueue(
        self,
        rollup_type: str,
        rollup_id: int,
        batch_id: Optional[Union[UUID, str]] = None,
    ) -> int:
        """Enqueue a 15-minute or daily rollup for backend upload."""
        if rollup_type not in ("15min", "daily"):
            raise ValueError(f"Invalid rollup_type '{rollup_type}'. Must be '15min' or 'daily'.")

        actual_batch_id = str(batch_id) if batch_id else str(uuid4())
        conn = self.db.get_connection()
        query = """
        INSERT INTO upload_queue (batch_id, rollup_type, rollup_id, status, attempts)
        VALUES (?, ?, ?, 'pending', 0);
        """
        params = (actual_batch_id, rollup_type, rollup_id)

        if self.db._is_memory:
            cur = conn.execute(query, params)
            conn.commit()
            return cur.lastrowid  # type: ignore[return-value]

        with conn:
            cur = conn.execute(query, params)
            return cur.lastrowid  # type: ignore[return-value]

    def fetch_pending(self, limit: int = 50) -> List[QueueItem]:
        """Fetch up to limit pending items from the queue."""
        conn = self.db.get_connection()
        cursor = conn.execute(
            """
            SELECT id, batch_id, rollup_type, rollup_id, status, attempts, last_attempt_at, created_at
            FROM upload_queue
            WHERE status = 'pending'
            ORDER BY id ASC
            LIMIT ?;
            """,
            (limit,),
        )
        items = []
        for row in cursor.fetchall():
            items.append(
                QueueItem(
                    id=row["id"],
                    batch_id=UUID(row["batch_id"]),
                    rollup_type=row["rollup_type"],
                    rollup_id=row["rollup_id"],
                    status=row["status"],
                    attempts=row["attempts"],
                    last_attempt_at=row["last_attempt_at"],
                    created_at=row["created_at"],
                )
            )
        return items

    def mark_uploading(self, queue_ids: List[int]) -> None:
        """Mark items as uploading and increment attempt counters."""
        if not queue_ids:
            return
        placeholders = ",".join("?" for _ in queue_ids)
        now_utc = datetime.now(timezone.utc).isoformat()
        conn = self.db.get_connection()
        query = f"""
        UPDATE upload_queue
        SET status = 'uploading',
            attempts = attempts + 1,
            last_attempt_at = ?
        WHERE id IN ({placeholders});
        """
        params = [now_utc] + queue_ids

        if self.db._is_memory:
            conn.execute(query, params)
            conn.commit()
        else:
            with conn:
                conn.execute(query, params)

    def mark_done(self, queue_ids: List[int]) -> None:
        """Mark items as successfully delivered."""
        if not queue_ids:
            return
        placeholders = ",".join("?" for _ in queue_ids)
        conn = self.db.get_connection()
        query = f"UPDATE upload_queue SET status = 'done' WHERE id IN ({placeholders});"

        if self.db._is_memory:
            conn.execute(query, queue_ids)
            conn.commit()
        else:
            with conn:
                conn.execute(query, queue_ids)

    def mark_failed(self, queue_ids: List[int]) -> None:
        """Mark items as failed to retry later."""
        if not queue_ids:
            return
        placeholders = ",".join("?" for _ in queue_ids)
        conn = self.db.get_connection()
        query = f"UPDATE upload_queue SET status = 'failed' WHERE id IN ({placeholders});"

        if self.db._is_memory:
            conn.execute(query, queue_ids)
            conn.commit()
        else:
            with conn:
                conn.execute(query, queue_ids)
