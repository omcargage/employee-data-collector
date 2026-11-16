"""Metric batch ingestion endpoints with schema validation and idempotency guarantees."""
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from edc_schemas import MetricBatch, Rollup15Min, RollupDaily
from edc_server.core.auth import get_authenticated_device
from edc_server.db.models import Device, MetricBatchRecord, MetricRollupRecord, utcnow
from edc_server.db.session import get_db

router = APIRouter(prefix="/metrics", tags=["Metrics"])


class IngestBatchResponse(BaseModel):
    status: str
    batch_id: str
    rollups_count: int
    message: str


@router.post("/batch", response_model=IngestBatchResponse, status_code=status.HTTP_201_CREATED)
def ingest_metric_batch(
    batch: MetricBatch,
    response: Response,
    device: Device = Depends(get_authenticated_device),
    db: Session = Depends(get_db),
) -> IngestBatchResponse:
    """Ingest aggregated 15-minute and daily metric rollups.

    Guarantees:
    - Identity derivation: Payload device_id MUST match the authenticated device.
    - Idempotency: Duplicate submissions of the same batch_id return 200 OK without double-inserting.
    - Schema validation: Enforced by shared MetricBatch Pydantic schema.
    """
    # 1. Identity Verification: Device cannot submit data claiming another machine or employee
    if batch.device_id != device.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Payload device_id '{batch.device_id}' does not match authenticated device '{device.id}'",
        )

    # 2. Idempotency Check by batch_id
    existing_batch = db.scalar(
        select(MetricBatchRecord).where(MetricBatchRecord.id == batch.batch_id)
    )
    if existing_batch:
        response.status_code = status.HTTP_200_OK
        return IngestBatchResponse(
            status="duplicate",
            batch_id=str(batch.batch_id),
            rollups_count=existing_batch.rollups_count,
            message="Batch has already been received and processed (idempotent response)",
        )

    # 3. Insert new batch record
    batch_record = MetricBatchRecord(
        id=batch.batch_id,
        device_id=device.id,
        schema_version=batch.schema_version,
        status="processed",
        received_at=utcnow(),
        rollups_count=len(batch.rollups),
    )
    db.add(batch_record)
    db.flush()

    # 4. Unpack and persist each individual rollup as native JSONB
    for rollup in batch.rollups:
        rollup_dict = rollup.model_dump(mode="json")

        if isinstance(rollup, Rollup15Min) or hasattr(rollup, "window_start"):
            rollup_type = "15min"
            window_start = getattr(rollup, "window_start", None)
            window_end = getattr(rollup, "window_end", None)
            logical_day = None
        else:
            rollup_type = "daily"
            window_start = None
            window_end = None
            logical_day = getattr(rollup, "logical_day", None)

        record = MetricRollupRecord(
            batch_id=batch.batch_id,
            rollup_type=rollup_type,
            window_start=window_start,
            window_end=window_end,
            logical_day=logical_day,
            coverage_ratio=float(rollup.coverage_ratio),
            low_coverage=bool(rollup.low_coverage),
            payload=rollup_dict,
            created_at=utcnow(),
        )
        db.add(record)

    # 5. Touch device last seen timestamp
    device.last_seen_at = utcnow()
    db.commit()

    return IngestBatchResponse(
        status="accepted",
        batch_id=str(batch.batch_id),
        rollups_count=len(batch.rollups),
        message=f"Successfully ingested {len(batch.rollups)} rollups",
    )
