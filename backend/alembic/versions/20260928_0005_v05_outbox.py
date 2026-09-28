"""Add transactional outbox for v0.5 event distribution.

Revision ID: 20260928_0005
Revises: 20260928_0004
Create Date: 2026-09-28
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "20260928_0005"
down_revision: Union[str, None] = "20260928_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())
    if "outbox_events" not in tables:
        op.create_table(
            "outbox_events",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("topic", sa.String(100), nullable=False),
            sa.Column("aggregate_type", sa.String(80), nullable=False),
            sa.Column("aggregate_id", sa.String(120), nullable=False),
            sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("status", sa.String(24), nullable=False, server_default="PENDING"),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_error", sa.String(500), nullable=True),
            sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        for name, cols in [
            ("ix_outbox_events_topic", ["topic"]),
            ("ix_outbox_events_aggregate_type", ["aggregate_type"]),
            ("ix_outbox_events_aggregate_id", ["aggregate_id"]),
            ("ix_outbox_events_status", ["status"]),
            ("ix_outbox_events_available_at", ["available_at"]),
            ("ix_outbox_events_published_at", ["published_at"]),
            ("ix_outbox_events_created_at", ["created_at"]),
        ]:
            op.create_index(name, "outbox_events", cols)


def downgrade() -> None:
    if "outbox_events" in set(inspect(op.get_bind()).get_table_names()):
        op.drop_table("outbox_events")
