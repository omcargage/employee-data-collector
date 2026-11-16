"""SQLAlchemy 2 declarative ORM models per Prompt 15 specification.

Defines schemas for:
- employees: Employee registry and organizational context.
- devices: Hardware instances mapped to employees.
- device_enrollments: Auth tokens and enrollment states.
- consent_records: Explicit informed consent audit trail.
- metric_batches: Ingestion batches uploaded from agent SQLite queues.
- metric_rollups: 15-minute and daily rollups stored as validated JSONB payloads.
- agent_heartbeats: Periodic agent alive pings.
"""
from datetime import date, datetime, timezone
from typing import List, Optional
import uuid

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from edc_server.db.session import Base


def utcnow() -> datetime:
    """Return timezone-aware current UTC datetime."""
    return datetime.now(timezone.utc)


class Employee(Base):
    """Employee record representing the user under telemetry monitoring."""
    __tablename__ = "employees"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    employee_code: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    department: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    devices: Mapped[List["Device"]] = relationship("Device", back_populates="employee", cascade="all, delete-orphan")
    consent_records: Mapped[List["ConsentRecord"]] = relationship("ConsentRecord", back_populates="employee", cascade="all, delete-orphan")
    enrollments: Mapped[List["DeviceEnrollment"]] = relationship("DeviceEnrollment", back_populates="employee", cascade="all, delete-orphan")


class Device(Base):
    """Enrolled hardware endpoint running the EDC desktop agent."""
    __tablename__ = "devices"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)  # Anonymized hardware UUID
    employee_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("employees.id", ondelete="CASCADE"), index=True, nullable=False)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)  # windows, macos, linux
    os_version: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    agent_version: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    employee: Mapped["Employee"] = relationship("Employee", back_populates="devices")
    enrollments: Mapped[List["DeviceEnrollment"]] = relationship("DeviceEnrollment", back_populates="device", cascade="all, delete-orphan")
    batches: Mapped[List["MetricBatchRecord"]] = relationship("MetricBatchRecord", back_populates="device", cascade="all, delete-orphan")
    heartbeats: Mapped[List["AgentHeartbeat"]] = relationship("AgentHeartbeat", back_populates="device", cascade="all, delete-orphan")


class DeviceEnrollment(Base):
    """Authentication token and credentials for an enrolled client device."""
    __tablename__ = "device_enrollments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    employee_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid, ForeignKey("employees.id", ondelete="CASCADE"), index=True, nullable=True)
    device_id: Mapped[Optional[str]] = mapped_column(String(128), ForeignKey("devices.id", ondelete="CASCADE"), index=True, nullable=True)
    token_hash: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    credential_hash: Mapped[Optional[str]] = mapped_column(String(255), unique=True, index=True, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)  # pending, enrolled, revoked
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    enrolled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    employee: Mapped[Optional["Employee"]] = relationship("Employee", back_populates="enrollments")
    device: Mapped[Optional["Device"]] = relationship("Device", back_populates="enrollments")


class ConsentRecord(Base):
    """Audit log of employee informed consent acknowledgements."""
    __tablename__ = "consent_records"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    employee_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("employees.id", ondelete="CASCADE"), index=True, nullable=False)
    consented_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)  # Notice version e.g. "1.0.0"
    status: Mapped[str] = mapped_column(String(32), default="consented", nullable=False)  # consented, revoked
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    employee: Mapped["Employee"] = relationship("Employee", back_populates="consent_records")


class MetricBatchRecord(Base):
    """Transmission batch envelope received from an agent client."""
    __tablename__ = "metric_batches"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)  # Matches batch_id in MetricBatch
    device_id: Mapped[str] = mapped_column(String(128), ForeignKey("devices.id", ondelete="CASCADE"), index=True, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), default="1.0.0", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="received", nullable=False)  # received, processed, rejected
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    rollups_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    device: Mapped["Device"] = relationship("Device", back_populates="batches")
    rollups: Mapped[List["MetricRollupRecord"]] = relationship("MetricRollupRecord", back_populates="batch", cascade="all, delete-orphan")


class MetricRollupRecord(Base):
    """Individual 15-minute or daily metric rollup stored as validated JSONB."""
    __tablename__ = "metric_rollups"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    batch_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("metric_batches.id", ondelete="CASCADE"), index=True, nullable=False)
    rollup_type: Mapped[str] = mapped_column(String(16), index=True, nullable=False)  # "15min" or "daily"
    window_start: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), index=True, nullable=True)
    window_end: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), index=True, nullable=True)
    logical_day: Mapped[Optional[date]] = mapped_column(Date, index=True, nullable=True)
    coverage_ratio: Mapped[float] = mapped_column(Float, nullable=False)
    low_coverage: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Native JSONB on PostgreSQL, JSON on SQLite
    payload: Mapped[dict] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    batch: Mapped["MetricBatchRecord"] = relationship("MetricBatchRecord", back_populates="rollups")

    __table_args__ = (
        Index("idx_metric_rollups_window_bounds", "window_start", "window_end"),
    )


class AgentHeartbeat(Base):
    """Agent health heartbeat ping stored for uptime analysis and crash detection."""
    __tablename__ = "agent_heartbeats"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    device_id: Mapped[str] = mapped_column(String(128), ForeignKey("devices.id", ondelete="CASCADE"), index=True, nullable=False)
    ts_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    agent_version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="collecting", nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    device: Mapped["Device"] = relationship("Device", back_populates="heartbeats")
