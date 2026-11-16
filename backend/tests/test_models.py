"""Tests for SQLAlchemy 2 models validating constraints, relationships, and JSONB serialization."""
from datetime import date, datetime, timedelta, timezone
import uuid
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from edc_schemas import Rollup15Min, RollupDaily, WindowBlocks
from edc_server.db.models import (
    AgentHeartbeat,
    ConsentRecord,
    Device,
    DeviceEnrollment,
    Employee,
    MetricBatchRecord,
    MetricRollupRecord,
)


def test_create_and_query_employee_and_device_relationship(db_session: Session):
    """Verify creating employee and device records linked by foreign key."""
    emp = Employee(
        employee_code="EMP-1001",
        name="John Doe",
        department="Engineering",
        is_active=True,
    )
    db_session.add(emp)
    db_session.flush()

    dev = Device(
        id="dev-win-abc-123",
        employee_id=emp.id,
        platform="windows",
        os_version="Windows 11 Build 22631",
        agent_version="0.1.0",
    )
    db_session.add(dev)
    db_session.commit()

    # Query back
    stmt = select(Employee).where(Employee.employee_code == "EMP-1001")
    retrieved_emp = db_session.scalar(stmt)
    assert retrieved_emp is not None
    assert len(retrieved_emp.devices) == 1
    assert retrieved_emp.devices[0].id == "dev-win-abc-123"
    assert retrieved_emp.devices[0].platform == "windows"


def test_device_enrollment_and_consent_records(db_session: Session):
    """Verify storing device enrollments and user consent history."""
    emp = Employee(
        employee_code="EMP-1002",
        name="Alice Smith",
        department="Product",
    )
    db_session.add(emp)
    db_session.flush()

    dev = Device(
        id="dev-mac-xyz-987",
        employee_id=emp.id,
        platform="macos",
    )
    db_session.add(dev)
    db_session.flush()

    # Device enrollment token
    enrollment = DeviceEnrollment(
        device_id=dev.id,
        token_hash="sha256:abc123tokenhashedvalue",
        status="enrolled",
    )
    db_session.add(enrollment)

    # Consent record
    consent = ConsentRecord(
        employee_id=emp.id,
        version="1.0.0",
        status="consented",
    )
    db_session.add(consent)
    db_session.commit()

    assert enrollment.id is not None
    assert consent.id is not None
    assert consent.status == "consented"
    assert enrollment.device.id == dev.id


def test_metric_batch_and_rollups_storing_shared_schemas(db_session: Session):
    """Verify metric_batches and metric_rollups store validated payloads reusing shared schemas."""
    emp = Employee(employee_code="EMP-1003", name="Bob Martin")
    db_session.add(emp)
    db_session.flush()

    dev = Device(id="dev-linux-456", employee_id=emp.id, platform="linux")
    db_session.add(dev)
    db_session.flush()

    batch_uuid = uuid.uuid4()
    batch = MetricBatchRecord(
        id=batch_uuid,
        device_id=dev.id,
        schema_version="1.0.0",
        status="received",
        rollups_count=2,
    )
    db_session.add(batch)
    db_session.flush()

    # 1. 15-Minute Rollup payload
    w_start = datetime(2026, 11, 16, 9, 0, tzinfo=timezone.utc)
    w_end = w_start + timedelta(minutes=15)
    r15 = Rollup15Min(
        schema_version="1.0.0",
        agent_version="0.1.0",
        window_start=w_start,
        window_end=w_end,
        coverage_ratio=0.98,
        low_coverage=False,
        gross_wpm=65.2,
        net_wpm=62.0,
        blocks=WindowBlocks(covered_s=900.0, n_char=250),
    )

    rollup_record_15 = MetricRollupRecord(
        batch_id=batch.id,
        rollup_type="15min",
        window_start=w_start,
        window_end=w_end,
        coverage_ratio=0.98,
        low_coverage=False,
        payload=r15.model_dump(mode="json"),
    )
    db_session.add(rollup_record_15)

    # 2. Daily Rollup payload
    day = date(2026, 11, 16)
    r_daily = RollupDaily(
        schema_version="1.0.0",
        agent_version="0.1.0",
        logical_day=day,
        coverage_ratio=0.92,
        low_coverage=False,
        after_hours_active_minutes=45.0,
        late_night_flag=False,
    )

    rollup_record_daily = MetricRollupRecord(
        batch_id=batch.id,
        rollup_type="daily",
        logical_day=day,
        coverage_ratio=0.92,
        low_coverage=False,
        payload=r_daily.model_dump(mode="json"),
    )
    db_session.add(rollup_record_daily)
    db_session.commit()

    # Assert retrieval and deserialization back into shared Pydantic models
    stmt = select(MetricBatchRecord).where(MetricBatchRecord.id == batch_uuid)
    retrieved_batch = db_session.scalar(stmt)
    assert retrieved_batch is not None
    assert len(retrieved_batch.rollups) == 2

    r15_retrieved = next(r for r in retrieved_batch.rollups if r.rollup_type == "15min")
    parsed_r15 = Rollup15Min.model_validate(r15_retrieved.payload)
    assert parsed_r15.gross_wpm == 65.2
    assert parsed_r15.blocks.n_char == 250

    daily_retrieved = next(r for r in retrieved_batch.rollups if r.rollup_type == "daily")
    parsed_daily = RollupDaily.model_validate(daily_retrieved.payload)
    assert parsed_daily.logical_day == day
    assert parsed_daily.after_hours_active_minutes == 45.0


def test_agent_heartbeat_creation(db_session: Session):
    """Verify recording and querying agent heartbeats."""
    emp = Employee(employee_code="EMP-1004", name="Charlie")
    db_session.add(emp)
    db_session.flush()

    dev = Device(id="dev-win-hb", employee_id=emp.id, platform="windows")
    db_session.add(dev)
    db_session.flush()

    hb_time = datetime.now(timezone.utc)
    hb = AgentHeartbeat(
        device_id=dev.id,
        ts_utc=hb_time,
        agent_version="0.1.0",
        status="collecting",
    )
    db_session.add(hb)
    db_session.commit()

    assert hb.id is not None
    assert hb.device.id == "dev-win-hb"


def test_cascade_delete_employee(db_session: Session):
    """Verify that deleting an employee cascades to devices, enrollments, and batches."""
    emp = Employee(employee_code="EMP-1005", name="David")
    db_session.add(emp)
    db_session.flush()

    dev = Device(id="dev-to-delete", employee_id=emp.id, platform="windows")
    db_session.add(dev)
    db_session.flush()

    batch = MetricBatchRecord(id=uuid.uuid4(), device_id=dev.id)
    db_session.add(batch)
    db_session.commit()

    # Delete employee
    db_session.delete(emp)
    db_session.commit()

    assert db_session.scalar(select(Device).where(Device.id == "dev-to-delete")) is None
    assert db_session.scalar(select(MetricBatchRecord).where(MetricBatchRecord.id == batch.id)) is None
