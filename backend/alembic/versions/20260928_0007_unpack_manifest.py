"""Add manifest-verified unpack sessions.

Revision ID: 20260928_0007
Revises: 20260928_0006
Create Date: 2026-09-28
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "20260928_0007"
down_revision: Union[str, None] = "20260928_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {col["name"] for col in inspect(bind).get_columns("unpack_sessions")}
    with op.batch_alter_table("unpack_sessions") as batch:
        if "source_ref" not in columns:
            batch.add_column(sa.Column("source_ref", sa.String(length=160), nullable=True))
        if "manifest_locked" not in columns:
            batch.add_column(
                sa.Column("manifest_locked", sa.Boolean(), nullable=False, server_default=sa.false())
            )
        if "expected_units" not in columns:
            batch.add_column(
                sa.Column("expected_units", sa.Integer(), nullable=False, server_default="0")
            )

    indexes = {idx["name"] for idx in inspect(bind).get_indexes("unpack_sessions")}
    if "ix_unpack_sessions_source_ref" not in indexes:
        op.create_index("ix_unpack_sessions_source_ref", "unpack_sessions", ["source_ref"])
    if "ix_unpack_sessions_manifest_locked" not in indexes:
        op.create_index("ix_unpack_sessions_manifest_locked", "unpack_sessions", ["manifest_locked"])

    if not inspect(bind).has_table("unpack_manifest_lines"):
        op.create_table(
            "unpack_manifest_lines",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("session_id", sa.String(length=36), sa.ForeignKey("unpack_sessions.id"), nullable=False),
            sa.Column("product_id", sa.String(length=36), sa.ForeignKey("products.id"), nullable=False),
            sa.Column("expected_qty", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("session_id", "product_id", name="uq_unpack_manifest_product"),
        )
        op.create_index("ix_unpack_manifest_lines_session_id", "unpack_manifest_lines", ["session_id"])
        op.create_index("ix_unpack_manifest_lines_product_id", "unpack_manifest_lines", ["product_id"])


def downgrade() -> None:
    bind = op.get_bind()
    if inspect(bind).has_table("unpack_manifest_lines"):
        op.drop_index("ix_unpack_manifest_lines_product_id", table_name="unpack_manifest_lines")
        op.drop_index("ix_unpack_manifest_lines_session_id", table_name="unpack_manifest_lines")
        op.drop_table("unpack_manifest_lines")

    indexes = {idx["name"] for idx in inspect(bind).get_indexes("unpack_sessions")}
    if "ix_unpack_sessions_manifest_locked" in indexes:
        op.drop_index("ix_unpack_sessions_manifest_locked", table_name="unpack_sessions")
    if "ix_unpack_sessions_source_ref" in indexes:
        op.drop_index("ix_unpack_sessions_source_ref", table_name="unpack_sessions")

    columns = {col["name"] for col in inspect(bind).get_columns("unpack_sessions")}
    with op.batch_alter_table("unpack_sessions") as batch:
        if "expected_units" in columns:
            batch.drop_column("expected_units")
        if "manifest_locked" in columns:
            batch.drop_column("manifest_locked")
        if "source_ref" in columns:
            batch.drop_column("source_ref")
