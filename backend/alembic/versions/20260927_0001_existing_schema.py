"""Existing FulfillOS schema baseline.

Revision ID: 20260927_0001
Revises:
Create Date: 2026-09-27

This revision intentionally contains no DDL. Existing production databases are
stamped to this revision after the current v0.3 schema is verified. Fresh
databases are created from SQLAlchemy metadata by the bootstrap migration runner
before being stamped, then all later revisions are applied normally.
"""

from typing import Sequence, Union

revision: str = "20260927_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
