"""Add enrollment tokens and device credential hash columns

Revision ID: 0002_enrollment_auth
Revises: 0001_initial_tables
Create Date: 2026-11-16 11:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0002_enrollment_auth"
down_revision: Union[str, None] = "0001_initial_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("device_enrollments") as batch_op:
        batch_op.add_column(sa.Column("employee_id", sa.Uuid(), nullable=True))
        batch_op.add_column(sa.Column("credential_hash", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False))
        batch_op.alter_column("device_id", existing_type=sa.String(length=128), nullable=True)
        batch_op.alter_column("enrolled_at", existing_type=sa.DateTime(timezone=True), nullable=True)
        batch_op.create_foreign_key("fk_device_enrollments_employee_id", "employees", ["employee_id"], ["id"], ondelete="CASCADE")
        batch_op.create_index("ix_device_enrollments_credential_hash", ["credential_hash"], unique=True)
        batch_op.create_index("ix_device_enrollments_employee_id", ["employee_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("device_enrollments") as batch_op:
        batch_op.drop_index("ix_device_enrollments_employee_id")
        batch_op.drop_index("ix_device_enrollments_credential_hash")
        batch_op.drop_constraint("fk_device_enrollments_employee_id", type_="foreignkey")
        batch_op.alter_column("enrolled_at", existing_type=sa.DateTime(timezone=True), nullable=False)
        batch_op.alter_column("device_id", existing_type=sa.String(length=128), nullable=False)
        batch_op.drop_column("created_at")
        batch_op.drop_column("credential_hash")
        batch_op.drop_column("employee_id")
