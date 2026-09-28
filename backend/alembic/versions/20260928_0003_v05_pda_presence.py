"""Persist live PDA activity for v0.5 presence.

Revision ID: 20260928_0003
Revises: 20260928_0002
Create Date: 2026-09-28
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "20260928_0003"
down_revision: Union[str, None] = "20260928_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    columns = {col["name"] for col in inspect(op.get_bind()).get_columns("device_telemetry")}
    if "activity" not in columns:
        with op.batch_alter_table("device_telemetry") as batch:
            batch.add_column(sa.Column("activity", sa.String(80), nullable=True))


def downgrade() -> None:
    columns = {col["name"] for col in inspect(op.get_bind()).get_columns("device_telemetry")}
    if "activity" in columns:
        with op.batch_alter_table("device_telemetry") as batch:
            batch.drop_column("activity")
