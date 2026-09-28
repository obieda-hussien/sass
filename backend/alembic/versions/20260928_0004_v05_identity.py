"""Add v0.5 identity lifecycle fields.

Revision ID: 20260928_0004
Revises: 20260928_0003
Create Date: 2026-09-28
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "20260928_0004"
down_revision: Union[str, None] = "20260928_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {col["name"] for col in inspect(bind).get_columns("users")}
    with op.batch_alter_table("users") as batch:
        if "must_change_password" not in columns:
            batch.add_column(
                sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.false())
            )
        if "deleted_at" not in columns:
            batch.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))

    indexes = {idx["name"] for idx in inspect(bind).get_indexes("users")}
    if "ix_users_must_change_password" not in indexes:
        op.create_index("ix_users_must_change_password", "users", ["must_change_password"])
    if "ix_users_deleted_at" not in indexes:
        op.create_index("ix_users_deleted_at", "users", ["deleted_at"])


def downgrade() -> None:
    bind = op.get_bind()
    indexes = {idx["name"] for idx in inspect(bind).get_indexes("users")}
    if "ix_users_deleted_at" in indexes:
        op.drop_index("ix_users_deleted_at", table_name="users")
    if "ix_users_must_change_password" in indexes:
        op.drop_index("ix_users_must_change_password", table_name="users")

    columns = {col["name"] for col in inspect(bind).get_columns("users")}
    with op.batch_alter_table("users") as batch:
        if "deleted_at" in columns:
            batch.drop_column("deleted_at")
        if "must_change_password" in columns:
            batch.drop_column("must_change_password")
