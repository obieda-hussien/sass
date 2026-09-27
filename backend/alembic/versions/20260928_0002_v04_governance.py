"""FulfillOS v0.4 workforce planning and execution governance.

Revision ID: 20260928_0002
Revises: 20260927_0001
Create Date: 2026-09-28
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "20260928_0002"
down_revision: Union[str, None] = "20260927_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables() -> set[str]:
    return set(inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {col["name"] for col in inspect(op.get_bind()).get_columns(table)}


def _create_index(name: str, table: str, columns: list[str], *, unique: bool = False) -> None:
    existing = {idx["name"] for idx in inspect(op.get_bind()).get_indexes(table)}
    if name not in existing:
        op.create_index(name, table, columns, unique=unique)


def upgrade() -> None:
    tables = _tables()

    if "shift_templates" not in tables:
        op.create_table(
            "shift_templates",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("site_id", sa.String(32), nullable=False, server_default="DEMO"),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("start_minute", sa.Integer(), nullable=False),
            sa.Column("end_minute", sa.Integer(), nullable=False),
            sa.Column("timezone_name", sa.String(80), nullable=False, server_default="Africa/Cairo"),
            sa.Column("break_minutes", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("grace_minutes", sa.Integer(), nullable=False, server_default="10"),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_by_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("site_id", "name", name="uq_shift_template_site_name"),
        )
        _create_index("ix_shift_templates_site_id", "shift_templates", ["site_id"])
        _create_index("ix_shift_templates_active", "shift_templates", ["active"])

    if "shift_assignments" not in tables:
        op.create_table(
            "shift_assignments",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("shift_template_id", sa.String(36), sa.ForeignKey("shift_templates.id"), nullable=True),
            sa.Column("shift_date", sa.Date(), nullable=False),
            sa.Column("scheduled_start_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("scheduled_end_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("status", sa.String(24), nullable=False, server_default="SCHEDULED"),
            sa.Column("notes", sa.String(300), nullable=True),
            sa.Column("created_by_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("user_id", "shift_date", name="uq_shift_assignment_user_date"),
        )
        _create_index("ix_shift_assignments_user_id", "shift_assignments", ["user_id"])
        _create_index("ix_shift_assignments_shift_date", "shift_assignments", ["shift_date"])
        _create_index("ix_shift_assignments_status", "shift_assignments", ["status"])

    if "break_sessions" not in tables:
        op.create_table(
            "break_sessions",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("shift_session_id", sa.String(36), sa.ForeignKey("shift_sessions.id"), nullable=True),
            sa.Column("break_type", sa.String(32), nullable=False, server_default="REST"),
            sa.Column("paid", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("duration_minutes", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        _create_index("ix_break_sessions_user_id", "break_sessions", ["user_id"])
        _create_index("ix_break_sessions_started_at", "break_sessions", ["started_at"])

    if "leave_requests" not in tables:
        op.create_table(
            "leave_requests",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("leave_type", sa.String(32), nullable=False, server_default="ANNUAL"),
            sa.Column("starts_on", sa.Date(), nullable=False),
            sa.Column("ends_on", sa.Date(), nullable=False),
            sa.Column("status", sa.String(24), nullable=False, server_default="PENDING"),
            sa.Column("reason", sa.String(300), nullable=True),
            sa.Column("reviewed_by_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        _create_index("ix_leave_requests_user_id", "leave_requests", ["user_id"])
        _create_index("ix_leave_requests_status", "leave_requests", ["status"])

    if "overtime_requests" not in tables:
        op.create_table(
            "overtime_requests",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("shift_assignment_id", sa.String(36), sa.ForeignKey("shift_assignments.id"), nullable=True),
            sa.Column("requested_minutes", sa.Integer(), nullable=False),
            sa.Column("approved_minutes", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("status", sa.String(24), nullable=False, server_default="PENDING"),
            sa.Column("reason", sa.String(300), nullable=True),
            sa.Column("reviewed_by_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        _create_index("ix_overtime_requests_user_id", "overtime_requests", ["user_id"])
        _create_index("ix_overtime_requests_status", "overtime_requests", ["status"])

    if "replenishment_events" not in tables:
        op.create_table(
            "replenishment_events",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("event_id", sa.String(80), nullable=False, unique=True),
            sa.Column("replenishment_task_id", sa.String(36), sa.ForeignKey("replenishment_tasks.id"), nullable=False),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("device_id", sa.String(80), sa.ForeignKey("devices.id"), nullable=True),
            sa.Column("event_type", sa.String(32), nullable=False),
            sa.Column("qty", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("source_location_id", sa.String(120), nullable=True),
            sa.Column("destination_location_id", sa.String(120), nullable=True),
            sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        _create_index("ix_replenishment_events_event_id", "replenishment_events", ["event_id"], unique=True)
        _create_index("ix_replenishment_events_task_id", "replenishment_events", ["replenishment_task_id"])

    if "role_permission_grants" not in tables:
        op.create_table(
            "role_permission_grants",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("role", sa.String(40), nullable=False),
            sa.Column("permission", sa.String(120), nullable=False),
            sa.Column("allowed", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_by_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("role", "permission", name="uq_role_permission"),
        )
        _create_index("ix_role_permission_grants_role", "role_permission_grants", ["role"])
        _create_index("ix_role_permission_grants_permission", "role_permission_grants", ["permission"])

    if "user_permission_grants" not in tables:
        op.create_table(
            "user_permission_grants",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("permission", sa.String(120), nullable=False),
            sa.Column("allowed", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_by_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("user_id", "permission", name="uq_user_permission"),
        )
        _create_index("ix_user_permission_grants_user_id", "user_permission_grants", ["user_id"])
        _create_index("ix_user_permission_grants_permission", "user_permission_grants", ["permission"])

    if "admin_audit_events" not in tables:
        op.create_table(
            "admin_audit_events",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("actor_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("action", sa.String(80), nullable=False),
            sa.Column("entity_type", sa.String(80), nullable=False),
            sa.Column("entity_id", sa.String(120), nullable=False),
            sa.Column("field_name", sa.String(120), nullable=True),
            sa.Column("old_value_json", sa.Text(), nullable=True),
            sa.Column("new_value_json", sa.Text(), nullable=True),
            sa.Column("reason", sa.String(300), nullable=True),
            sa.Column("request_id", sa.String(80), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        _create_index("ix_admin_audit_events_actor_user_id", "admin_audit_events", ["actor_user_id"])
        _create_index("ix_admin_audit_events_action", "admin_audit_events", ["action"])
        _create_index("ix_admin_audit_events_entity", "admin_audit_events", ["entity_type", "entity_id"])
        _create_index("ix_admin_audit_events_created_at", "admin_audit_events", ["created_at"])

    if "replenishment_tasks" in _tables():
        cols = _columns("replenishment_tasks")
        additions = [
            ("assigned_by_user_id", sa.String(36)),
            ("priority", sa.Integer()),
            ("actual_qty", sa.Integer()),
            ("version", sa.Integer()),
            ("claimed_at", sa.DateTime(timezone=True)),
            ("started_at", sa.DateTime(timezone=True)),
            ("source_scanned_at", sa.DateTime(timezone=True)),
            ("destination_scanned_at", sa.DateTime(timezone=True)),
            ("cancelled_at", sa.DateTime(timezone=True)),
            ("failure_reason", sa.String(240)),
        ]
        with op.batch_alter_table("replenishment_tasks") as batch:
            for name, type_ in additions:
                if name not in cols:
                    nullable = name not in {"priority", "actual_qty", "version"}
                    server_default = None
                    if name == "priority":
                        server_default = "50"
                    elif name == "actual_qty":
                        server_default = "0"
                    elif name == "version":
                        server_default = "1"
                    batch.add_column(sa.Column(name, type_, nullable=nullable, server_default=server_default))
        _create_index("ix_replenishment_tasks_priority", "replenishment_tasks", ["priority"])


def downgrade() -> None:
    # Downgrade is intentionally conservative for warehouse data. Only v0.4
    # extension tables are removed; existing replenishment execution columns are
    # retained to avoid destructive loss of audit history.
    for table in [
        "admin_audit_events",
        "user_permission_grants",
        "role_permission_grants",
        "replenishment_events",
        "overtime_requests",
        "leave_requests",
        "break_sessions",
        "shift_assignments",
        "shift_templates",
    ]:
        if table in _tables():
            op.drop_table(table)
