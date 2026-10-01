"""Printable inbound manifests and auditable shipment issues."""
from alembic import op
import sqlalchemy as sa

revision = "20261001_0009"
down_revision = "20260928_0008"
branch_labels = None
depends_on = None


def upgrade():
    for name, kind in [
        ("supplier_name", sa.String(160)), ("purchase_order_ref", sa.String(120)),
        ("order_date", sa.Date()), ("delivery_from", sa.Date()), ("delivery_to", sa.Date()),
        ("shipping_address", sa.String(500)), ("notes", sa.String(1000)),
    ]:
        op.add_column("shipments", sa.Column(name, kind, nullable=True))
    op.create_table(
        "shipment_issues",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("event_id", sa.String(120), nullable=False),
        sa.Column("shipment_id", sa.String(36), sa.ForeignKey("shipments.id"), nullable=False),
        sa.Column("product_id", sa.String(36), sa.ForeignKey("products.id"), nullable=True),
        sa.Column("issue_type", sa.String(32), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("notes", sa.String(1000), nullable=False),
        sa.Column("lot_code", sa.String(80), nullable=True),
        sa.Column("expires_on", sa.Date(), nullable=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("device_id", sa.String(120), sa.ForeignKey("devices.id"), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="OPEN"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_by_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution", sa.String(1000), nullable=True),
    )
    op.create_index("ix_shipment_issues_event_id", "shipment_issues", ["event_id"], unique=True)
    op.create_index("ix_shipment_issues_shipment_id", "shipment_issues", ["shipment_id"])
    op.create_index("ix_shipment_issues_status", "shipment_issues", ["status"])
    op.create_table("shipment_scan_receipts",
        sa.Column("event_key", sa.String(64), primary_key=True),
        sa.Column("shipment_id", sa.String(36), sa.ForeignKey("shipments.id"), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_shipment_scan_receipts_shipment_id", "shipment_scan_receipts", ["shipment_id"])


def downgrade():
    op.drop_table("shipment_scan_receipts")
    op.drop_table("shipment_issues")
    for name in ["notes", "shipping_address", "delivery_to", "delivery_from", "order_date", "purchase_order_ref", "supplier_name"]:
        op.drop_column("shipments", name)
