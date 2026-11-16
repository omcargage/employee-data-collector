"""Batch builder for grouping queued metric rollups into schema-validated MetricBatch payloads."""
import logging
from typing import List, Optional, Tuple
from uuid import UUID, uuid4

from edc_agent.client.device_identity import get_or_create_device_id
from edc_agent.storage.database import Database
from edc_agent.storage.queue import QueueItem, UploadQueue
from edc_schemas import MetricBatch, Rollup15Min, RollupDaily

logger = logging.getLogger("edc_agent.client.batch_builder")


def build_batch_from_queue(
    db: Database,
    queue: UploadQueue,
    device_id: Optional[str] = None,
    batch_size: int = 20,
) -> Optional[Tuple[MetricBatch, List[int]]]:
    """Assemble a MetricBatch payload from pending or failed upload queue items.

    Args:
        db: SQLite Database instance containing rollups.
        queue: UploadQueue instance managing outbound delivery queue.
        device_id: Optional explicit hardware device UUID. If omitted, resolved from agent_state.
        batch_size: Maximum number of rollups to include in a single batch transmission.

    Returns:
        A tuple of (MetricBatch, list_of_queue_item_ids) or None if the queue is empty.
    """
    items = queue.fetch_pending(limit=batch_size, include_failed=True)
    if not items:
        return None

    # Check if all items in this slice already share a common batch_id from a prior attempt
    first_batch_id = items[0].batch_id
    if len(items) > 1 and all(item.batch_id == first_batch_id for item in items):
        batch_id = first_batch_id
    elif len(items) == 1 and items[0].attempts > 0:
        # Retry with the same batch_id to enable server-side idempotent duplicate detection
        batch_id = first_batch_id
    else:
        # Generate new batch identifier
        batch_id = uuid4()

    actual_device_id = device_id or get_or_create_device_id(db)
    rollups = []
    included_queue_ids: List[int] = []

    for item in items:
        rollup = None
        if item.rollup_type == "15min":
            rollup = db.get_rollup_15min(item.rollup_id)
        elif item.rollup_type == "daily":
            rollup = db.get_rollup_daily_by_id(item.rollup_id)
        else:
            logger.warning("Unrecognized rollup_type '%s' for queue item id=%d; skipping.", item.rollup_type, item.id)
            continue

        if rollup is None:
            logger.warning(
                "Queue item id=%d referenced missing %s rollup (id=%d); skipping.",
                item.id,
                item.rollup_type,
                item.rollup_id,
            )
            continue

        rollups.append(rollup)
        included_queue_ids.append(item.id)

    if not rollups:
        logger.warning("No valid rollups could be loaded for pending queue items.")
        return None

    batch = MetricBatch(
        batch_id=batch_id,
        device_id=actual_device_id,
        schema_version="1.0.0",
        rollups=rollups,
    )

    return batch, included_queue_ids
