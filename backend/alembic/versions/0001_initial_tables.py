"""Create initial schema for employees, devices, enrollments, consent, batches, rollups, heartbeats

Revision ID: 0001_initial_tables
Revises: 
Create Date: 2026-11-16 10:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_tables"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Employees table
    op.create_table(
        "employees",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("employee_code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("department", sa.String(length=128), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_employees_employee_code", "employees", ["employee_code"], unique=True)

    # 2. Devices table
    op.create_table(
        "devices",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("employee_id", sa.Uuid(), nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("os_version", sa.String(length=128), nullable=True),
        sa.Column("agent_version", sa.String(length=64), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_devices_employee_id", "devices", ["employee_id"], unique=False)

    # 3. Device Enrollments table
    op.create_table(
        "device_enrollments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.String(length=128), nullable=False),
        sa.Column("token_hash", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="enrolled", nullable=False),
        sa.Column("enrolled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_device_enrollments_device_id", "device_enrollments", ["device_id"], unique=False)
    op.create_index("ix_device_enrollments_token_hash", "device_enrollments", ["token_hash"], unique=True)

    # 4. Consent Records table
    op.create_table(
        "consent_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("employee_id", sa.Uuid(), nullable=False),
        sa.Column("consented_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="consented", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_consent_records_employee_id", "consent_records", ["employee_id"], unique=False)

    # 5. Metric Batches table
    op.create_table(
        "metric_batches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.String(length=128), nullable=False),
        sa.Column("schema_version", sa.String(length=32), server_default="1.0.0", nullable=False),
        sa.Column("status", sa.String(length=32), server_default="received", nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rollups_count", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_metric_batches_device_id", "metric_batches", ["device_id"], unique=False)

    # 6. Metric Rollups table (JSONB payload)
    op.create_table(
        "metric_rollups",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("rollup_type", sa.String(length=16), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("logical_day", sa.Date(), nullable=True),
        sa.Column("coverage_ratio", sa.Float(), nullable=False),
        sa.Column("low_coverage", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "payload",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["batch_id"], ["metric_batches.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_metric_rollups_batch_id", "metric_rollups", ["batch_id"], unique=False)
    op.create_index("ix_metric_rollups_rollup_type", "metric_rollups", ["rollup_type"], unique=False)
    op.create_index("ix_metric_rollups_window_start", "metric_rollups", ["window_start"], unique=False)
    op.create_index("ix_metric_rollups_window_end", "metric_rollups", ["window_end"], unique=False)
    op.create_index("ix_metric_rollups_logical_day", "metric_rollups", ["logical_day"], unique=False)
    op.create_index("idx_metric_rollups_window_bounds", "metric_rollups", ["window_start", "window_end"], unique=False)

    # 7. Agent Heartbeats table
    op.create_table(
        "agent_heartbeats",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.String(length=128), nullable=False),
        sa.Column("ts_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("agent_version", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="collecting", nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_heartbeats_device_id", "agent_heartbeats", ["device_id"], unique=False)
    op.create_index("ix_agent_heartbeats_ts_utc", "agent_heartbeats", ["ts_utc"], unique=False)


def downgrade() -> None:
    op.drop_table("agent_heartbeats")
    op.drop_table("metric_rollups")
    op.drop_table("metric_batches")
    op.drop_table("consent_records")
    op.drop_table("device_enrollments")
    op.drop_table("devices")
    op.drop_table("employees")
