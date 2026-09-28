"""Enforce case-insensitive username uniqueness.

Revision ID: 20260928_0006
Revises: 20260928_0005
Create Date: 2026-09-28
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text

revision: str = "20260928_0006"
down_revision: Union[str, None] = "20260928_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


INDEX_NAME = "uq_users_username_ci"


def upgrade() -> None:
    bind = op.get_bind()
    duplicates = bind.execute(
        text(
            """
            SELECT lower(username) AS normalized, count(*) AS n
            FROM users
            GROUP BY lower(username)
            HAVING count(*) > 1
            LIMIT 1
            """
        )
    ).first()
    if duplicates is not None:
        raise RuntimeError(
            "Cannot enforce case-insensitive username uniqueness: "
            f"duplicate normalized username {duplicates.normalized!r} exists"
        )

    indexes = {idx["name"] for idx in inspect(bind).get_indexes("users")}
    if INDEX_NAME not in indexes:
        op.create_index(
            INDEX_NAME,
            "users",
            [sa.text("lower(username)")],
            unique=True,
        )


def downgrade() -> None:
    indexes = {idx["name"] for idx in inspect(op.get_bind()).get_indexes("users")}
    if INDEX_NAME in indexes:
        op.drop_index(INDEX_NAME, table_name="users")
