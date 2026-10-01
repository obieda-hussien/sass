"""Track order-level unpack claims and inbound temperature at opening.

Revision ID: 20260928_0008
Revises: 20260928_0007
"""

from alembic import op
import sqlalchemy as sa

revision = "20260928_0008"
down_revision = "20260928_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("unpack_sessions", sa.Column("source_order_id", sa.String(36), sa.ForeignKey("orders.id"), nullable=True))
    op.create_index("ix_unpack_sessions_source_order_id", "unpack_sessions", ["source_order_id"])
    op.create_index("uq_unpack_order_temperature", "unpack_sessions", ["source_order_id", "temperature_class"], unique=True)
    op.add_column("shipments", sa.Column("opening_temperature_c", sa.Float(), nullable=True))
    op.add_column("shipment_lines", sa.Column("discrepancy_reason", sa.String(240), nullable=True))
    op.add_column("shipment_lines", sa.Column("adhoc_stowed_qty", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("shipment_lines", "adhoc_stowed_qty")
    op.drop_column("shipment_lines", "discrepancy_reason")
    op.drop_column("shipments", "opening_temperature_c")
    op.drop_index("uq_unpack_order_temperature", table_name="unpack_sessions")
    op.drop_index("ix_unpack_sessions_source_order_id", table_name="unpack_sessions")
    op.drop_column("unpack_sessions", "source_order_id")
