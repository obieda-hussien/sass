from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import EmployeeProfile, User
from ..models_ops import (
    ActivePickLease,
    AdminAuditEvent,
    BreakSession,
    LeaveRequest,
    OvertimeRequest,
    RolePermissionGrant,
    ShiftAssignment,
    ShiftSession,
    ShiftTemplate,
    UserPermissionGrant,
)
from .ops_platform import OpsError, clock_in_shift, clock_out_shift, get_worker_state, set_worker_state


DEFAULT_ROLE_PERMISSIONS: dict[str, set[str]] = {
    "ADMIN": {"*"},
    "SUPERVISOR": {
        "operations.manage",
        "operations.read",
        "employees.read",
        "employees.write",
        "attendance.approve",
        "payroll.read",
        "payroll.adjust",
        "password_reset.resolve",
        "shifts.manage",
        "replenishment.manage",
        "permissions.manage",
        "audit.read",
    },
    "INVENTORY": {
        "inventory.read",
        "inventory.write",
        "cycle_count.execute",
        "replenishment.execute",
    },
    "RECEIVER": {
        "inventory.read",
        "receiving.execute",
        "stow.execute",
    },
    "SENIOR_PICKER": {
        "orders.pick",
        "inventory.read",
        "replenishment.execute",
    },
    "PICKER": {
        "orders.pick",
        "inventory.read",
    },
}


class GovernanceError(RuntimeError):
    def __init__(self, message: str, code: str = "GOVERNANCE_ERROR"):
        super().__init__(message)
        self.code = code


def _json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True, default=str)


def audit_event(
    db: Session,
    *,
    actor_user_id: str | None,
    action: str,
    entity_type: str,
    entity_id: str,
    field_name: str | None = None,
    old_value: Any = None,
    new_value: Any = None,
    reason: str | None = None,
    request_id: str | None = None,
) -> AdminAuditEvent:
    event = AdminAuditEvent(
        actor_user_id=actor_user_id,
        action=action.strip().upper(),
        entity_type=entity_type.strip().upper(),
        entity_id=entity_id,
        field_name=field_name,
        old_value_json=None if old_value is None else _json(old_value),
        new_value_json=None if new_value is None else _json(new_value),
        reason=reason,
        request_id=request_id,
    )
    db.add(event)
    db.flush()
    return event


def has_permission(db: Session, user: User, permission: str) -> bool:
    permission = permission.strip().lower()

    user_override = db.scalar(
        select(UserPermissionGrant).where(
            UserPermissionGrant.user_id == user.id,
            UserPermissionGrant.permission == permission,
        )
    )
    if user_override is not None:
        return bool(user_override.allowed)

    role = user.role.strip().upper()
    role_override = db.scalar(
        select(RolePermissionGrant).where(
            RolePermissionGrant.role == role,
            RolePermissionGrant.permission == permission,
        )
    )
    if role_override is not None:
        return bool(role_override.allowed)

    defaults = DEFAULT_ROLE_PERMISSIONS.get(role, set())
    return "*" in defaults or permission in defaults


def require_permission(db: Session, user: User, permission: str) -> None:
    if not has_permission(db, user, permission):
        raise GovernanceError(
            f"Permission required: {permission}",
            "PERMISSION_DENIED",
        )


def effective_permissions(db: Session, user: User) -> dict[str, Any]:
    role = user.role.strip().upper()
    defaults = set(DEFAULT_ROLE_PERMISSIONS.get(role, set()))
    role_rows = db.scalars(select(RolePermissionGrant).where(RolePermissionGrant.role == role)).all()
    user_rows = db.scalars(select(UserPermissionGrant).where(UserPermissionGrant.user_id == user.id)).all()

    effective = set(defaults)
    for row in role_rows:
        if row.allowed:
            effective.add(row.permission)
        else:
            effective.discard(row.permission)
    for row in user_rows:
        if row.allowed:
            effective.add(row.permission)
        else:
            effective.discard(row.permission)

    return {
        "user_id": user.id,
        "role": role,
        "permissions": sorted(effective),
        "role_overrides": [
            {"permission": row.permission, "allowed": row.allowed}
            for row in role_rows
        ],
        "user_overrides": [
            {"permission": row.permission, "allowed": row.allowed}
            for row in user_rows
        ],
    }


def set_role_permission(
    db: Session,
    *,
    role: str,
    permission: str,
    allowed: bool,
    actor_user_id: str,
) -> RolePermissionGrant:
    role_value = role.strip().upper()
    perm = permission.strip().lower()
    row = db.scalar(
        select(RolePermissionGrant).where(
            RolePermissionGrant.role == role_value,
            RolePermissionGrant.permission == perm,
        )
    )
    old = None if row is None else row.allowed
    if row is None:
        row = RolePermissionGrant(
            role=role_value,
            permission=perm,
            allowed=allowed,
            created_by_user_id=actor_user_id,
        )
        db.add(row)
    else:
        row.allowed = allowed
        row.created_by_user_id = actor_user_id
    db.flush()
    audit_event(
        db,
        actor_user_id=actor_user_id,
        action="SET_ROLE_PERMISSION",
        entity_type="ROLE_PERMISSION",
        entity_id=f"{role_value}:{perm}",
        old_value=old,
        new_value=allowed,
    )
    return row


def set_user_permission(
    db: Session,
    *,
    user_id: str,
    permission: str,
    allowed: bool,
    actor_user_id: str,
) -> UserPermissionGrant:
    if db.get(User, user_id) is None:
        raise GovernanceError("User not found", "USER_NOT_FOUND")
    perm = permission.strip().lower()
    row = db.scalar(
        select(UserPermissionGrant).where(
            UserPermissionGrant.user_id == user_id,
            UserPermissionGrant.permission == perm,
        )
    )
    old = None if row is None else row.allowed
    if row is None:
        row = UserPermissionGrant(
            user_id=user_id,
            permission=perm,
            allowed=allowed,
            created_by_user_id=actor_user_id,
        )
        db.add(row)
    else:
        row.allowed = allowed
        row.created_by_user_id = actor_user_id
    db.flush()
    audit_event(
        db,
        actor_user_id=actor_user_id,
        action="SET_USER_PERMISSION",
        entity_type="USER_PERMISSION",
        entity_id=f"{user_id}:{perm}",
        old_value=old,
        new_value=allowed,
    )
    return row


def create_shift_template(
    db: Session,
    *,
    site_id: str,
    name: str,
    start_minute: int,
    end_minute: int,
    timezone_name: str,
    break_minutes: int,
    grace_minutes: int,
    actor_user_id: str,
) -> ShiftTemplate:
    if not 0 <= start_minute <= 1439 or not 0 <= end_minute <= 1439:
        raise GovernanceError("Shift minutes must be between 0 and 1439", "BAD_SHIFT_TIME")
    if break_minutes < 0 or grace_minutes < 0:
        raise GovernanceError("Break/grace minutes cannot be negative", "BAD_SHIFT_POLICY")
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise GovernanceError("Unknown timezone", "BAD_TIMEZONE") from exc

    existing = db.scalar(
        select(ShiftTemplate).where(
            ShiftTemplate.site_id == site_id.strip().upper(),
            ShiftTemplate.name == name.strip(),
        )
    )
    if existing:
        raise GovernanceError("Shift template name already exists", "SHIFT_TEMPLATE_EXISTS")

    row = ShiftTemplate(
        site_id=site_id.strip().upper(),
        name=name.strip(),
        start_minute=start_minute,
        end_minute=end_minute,
        timezone_name=timezone_name,
        break_minutes=break_minutes,
        grace_minutes=grace_minutes,
        created_by_user_id=actor_user_id,
    )
    db.add(row)
    db.flush()
    audit_event(
        db,
        actor_user_id=actor_user_id,
        action="CREATE_SHIFT_TEMPLATE",
        entity_type="SHIFT_TEMPLATE",
        entity_id=row.id,
        new_value={
            "site_id": row.site_id,
            "name": row.name,
            "start_minute": row.start_minute,
            "end_minute": row.end_minute,
            "timezone_name": row.timezone_name,
            "break_minutes": row.break_minutes,
            "grace_minutes": row.grace_minutes,
        },
    )
    return row


def _assignment_window(template: ShiftTemplate, shift_date: date) -> tuple[datetime, datetime]:
    zone = ZoneInfo(template.timezone_name)
    start_local = datetime(
        shift_date.year,
        shift_date.month,
        shift_date.day,
        template.start_minute // 60,
        template.start_minute % 60,
        tzinfo=zone,
    )
    end_date = shift_date + timedelta(days=1 if template.end_minute <= template.start_minute else 0)
    end_local = datetime(
        end_date.year,
        end_date.month,
        end_date.day,
        template.end_minute // 60,
        template.end_minute % 60,
        tzinfo=zone,
    )
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def assign_shift(
    db: Session,
    *,
    user_id: str,
    shift_template_id: str,
    shift_date: date,
    actor_user_id: str,
    notes: str | None = None,
) -> ShiftAssignment:
    user = db.get(User, user_id)
    template = db.get(ShiftTemplate, shift_template_id)
    if user is None:
        raise GovernanceError("User not found", "USER_NOT_FOUND")
    if template is None or not template.active:
        raise GovernanceError("Shift template not found or inactive", "SHIFT_TEMPLATE_NOT_FOUND")

    start, end = _assignment_window(template, shift_date)
    existing = db.scalar(
        select(ShiftAssignment).where(
            ShiftAssignment.user_id == user_id,
            ShiftAssignment.shift_date == shift_date,
        )
    )
    if existing:
        old = {
            "template": existing.shift_template_id,
            "start": existing.scheduled_start_at.isoformat(),
            "end": existing.scheduled_end_at.isoformat(),
            "status": existing.status,
        }
        existing.shift_template_id = template.id
        existing.scheduled_start_at = start
        existing.scheduled_end_at = end
        existing.status = "SCHEDULED"
        existing.notes = notes
        existing.created_by_user_id = actor_user_id
        row = existing
        action = "UPDATE_SHIFT_ASSIGNMENT"
    else:
        row = ShiftAssignment(
            user_id=user_id,
            shift_template_id=template.id,
            shift_date=shift_date,
            scheduled_start_at=start,
            scheduled_end_at=end,
            status="SCHEDULED",
            notes=notes,
            created_by_user_id=actor_user_id,
        )
        db.add(row)
        old = None
        action = "CREATE_SHIFT_ASSIGNMENT"

    db.flush()
    audit_event(
        db,
        actor_user_id=actor_user_id,
        action=action,
        entity_type="SHIFT_ASSIGNMENT",
        entity_id=row.id,
        old_value=old,
        new_value={
            "user_id": user_id,
            "template": template.id,
            "shift_date": shift_date.isoformat(),
            "start": start.isoformat(),
            "end": end.isoformat(),
        },
    )
    return row


def roster(
    db: Session,
    *,
    from_date: date,
    to_date: date,
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    query = (
        select(ShiftAssignment)
        .where(
            ShiftAssignment.shift_date >= from_date,
            ShiftAssignment.shift_date <= to_date,
        )
        .order_by(ShiftAssignment.shift_date, ShiftAssignment.scheduled_start_at)
    )
    if user_id:
        query = query.where(ShiftAssignment.user_id == user_id)
    rows = db.scalars(query).all()
    result = []
    for row in rows:
        user = db.get(User, row.user_id)
        template = db.get(ShiftTemplate, row.shift_template_id) if row.shift_template_id else None
        result.append({
            "id": row.id,
            "user_id": row.user_id,
            "username": user.username if user else None,
            "shift_date": row.shift_date.isoformat(),
            "template_id": row.shift_template_id,
            "template_name": template.name if template else None,
            "scheduled_start_at": row.scheduled_start_at.isoformat(),
            "scheduled_end_at": row.scheduled_end_at.isoformat(),
            "status": row.status,
            "notes": row.notes,
        })
    return result


def assignment_for_clock_in(db: Session, user_id: str, at: datetime | None = None) -> ShiftAssignment:
    now = at or datetime.now(timezone.utc)
    window_start = now - timedelta(hours=8)
    window_end = now + timedelta(hours=8)
    row = db.scalar(
        select(ShiftAssignment)
        .where(
            ShiftAssignment.user_id == user_id,
            ShiftAssignment.status.in_(["SCHEDULED", "CLOCKED_IN"]),
            ShiftAssignment.scheduled_start_at <= window_end,
            ShiftAssignment.scheduled_end_at >= window_start,
        )
        .order_by(ShiftAssignment.scheduled_start_at)
        .limit(1)
    )
    if row is None:
        raise GovernanceError("No scheduled shift near the current time", "NO_SCHEDULED_SHIFT")
    return row


def auto_clock_in(db: Session, *, user_id: str, at: datetime | None = None) -> dict[str, Any]:
    assignment = assignment_for_clock_in(db, user_id, at)
    template = db.get(ShiftTemplate, assignment.shift_template_id) if assignment.shift_template_id else None
    profile = db.get(EmployeeProfile, user_id)
    old_grace = profile.grace_minutes if profile else None
    if profile and template:
        profile.grace_minutes = template.grace_minutes
    try:
        shift = clock_in_shift(
            db,
            user_id=user_id,
            scheduled_start_at=assignment.scheduled_start_at,
            scheduled_end_at=assignment.scheduled_end_at,
            clock_in_at=at,
        )
    finally:
        if profile and old_grace is not None:
            profile.grace_minutes = old_grace
    assignment.status = "CLOCKED_IN"
    db.flush()
    return {
        "assignment_id": assignment.id,
        "shift_id": shift.id,
        "late_minutes": shift.late_minutes,
        "clock_in_at": shift.clock_in_at.isoformat(),
    }


def auto_clock_out(db: Session, *, user_id: str, at: datetime | None = None) -> dict[str, Any]:
    shift = clock_out_shift(db, user_id=user_id, clock_out_at=at)
    assignment = db.scalar(
        select(ShiftAssignment)
        .where(
            ShiftAssignment.user_id == user_id,
            ShiftAssignment.scheduled_start_at == shift.scheduled_start_at,
            ShiftAssignment.scheduled_end_at == shift.scheduled_end_at,
        )
        .limit(1)
    )
    if assignment:
        assignment.status = "COMPLETED"
    db.flush()
    return {
        "assignment_id": assignment.id if assignment else None,
        "shift_id": shift.id,
        "worked_minutes": shift.worked_minutes,
        "late_minutes": shift.late_minutes,
        "early_leave_minutes": shift.early_leave_minutes,
        "overtime_minutes": shift.overtime_minutes,
        "clock_out_at": shift.clock_out_at.isoformat() if shift.clock_out_at else None,
    }


def start_break(
    db: Session,
    *,
    user_id: str,
    break_type: str = "REST",
    paid: bool = True,
) -> BreakSession:
    if db.get(ActivePickLease, user_id):
        raise GovernanceError("Cannot start break with an active order", "ACTIVE_PICK_EXISTS")
    open_break = db.scalar(
        select(BreakSession)
        .where(BreakSession.user_id == user_id, BreakSession.ended_at.is_(None))
        .order_by(BreakSession.started_at.desc())
    )
    if open_break:
        return open_break
    shift = db.scalar(
        select(ShiftSession)
        .where(ShiftSession.user_id == user_id, ShiftSession.status == "OPEN")
        .order_by(ShiftSession.created_at.desc())
    )
    row = BreakSession(
        user_id=user_id,
        shift_session_id=shift.id if shift else None,
        break_type=break_type.strip().upper(),
        paid=paid,
    )
    db.add(row)
    set_worker_state(db, user_id, "BREAK", activity_ref=row.id, reason=row.break_type)
    db.flush()
    return row


def end_break(db: Session, *, user_id: str) -> BreakSession:
    row = db.scalar(
        select(BreakSession)
        .where(BreakSession.user_id == user_id, BreakSession.ended_at.is_(None))
        .order_by(BreakSession.started_at.desc())
    )
    if row is None:
        raise GovernanceError("No open break", "NO_OPEN_BREAK")
    now = datetime.now(timezone.utc)
    row.ended_at = now
    started = row.started_at if row.started_at.tzinfo else row.started_at.replace(tzinfo=timezone.utc)
    row.duration_minutes = max(0, int((now - started).total_seconds() // 60))
    set_worker_state(db, user_id, "AVAILABLE", reason="BREAK_ENDED", force=True)
    db.flush()
    return row


def create_leave_request(
    db: Session,
    *,
    user_id: str,
    leave_type: str,
    starts_on: date,
    ends_on: date,
    reason: str | None,
) -> LeaveRequest:
    if ends_on < starts_on:
        raise GovernanceError("Leave end date cannot precede start date", "BAD_LEAVE_WINDOW")
    row = LeaveRequest(
        user_id=user_id,
        leave_type=leave_type.strip().upper(),
        starts_on=starts_on,
        ends_on=ends_on,
        reason=reason,
    )
    db.add(row)
    db.flush()
    return row


def review_leave_request(
    db: Session,
    *,
    request_id: str,
    approved: bool,
    reviewer_id: str,
) -> LeaveRequest:
    row = db.get(LeaveRequest, request_id)
    if row is None or row.status != "PENDING":
        raise GovernanceError("Pending leave request not found", "LEAVE_NOT_PENDING")
    row.status = "APPROVED" if approved else "REJECTED"
    row.reviewed_by_user_id = reviewer_id
    row.reviewed_at = datetime.now(timezone.utc)
    if approved:
        assignments = db.scalars(
            select(ShiftAssignment).where(
                ShiftAssignment.user_id == row.user_id,
                ShiftAssignment.shift_date >= row.starts_on,
                ShiftAssignment.shift_date <= row.ends_on,
                ShiftAssignment.status == "SCHEDULED",
            )
        ).all()
        for assignment in assignments:
            assignment.status = "LEAVE"
    db.flush()
    audit_event(
        db,
        actor_user_id=reviewer_id,
        action="REVIEW_LEAVE",
        entity_type="LEAVE_REQUEST",
        entity_id=row.id,
        new_value={"status": row.status},
    )
    return row


def create_overtime_request(
    db: Session,
    *,
    user_id: str,
    requested_minutes: int,
    shift_assignment_id: str | None,
    reason: str | None,
) -> OvertimeRequest:
    if requested_minutes <= 0:
        raise GovernanceError("Overtime minutes must be positive", "BAD_OVERTIME")
    row = OvertimeRequest(
        user_id=user_id,
        shift_assignment_id=shift_assignment_id,
        requested_minutes=requested_minutes,
        reason=reason,
    )
    db.add(row)
    db.flush()
    return row


def review_overtime_request(
    db: Session,
    *,
    request_id: str,
    approved_minutes: int,
    reviewer_id: str,
) -> OvertimeRequest:
    row = db.get(OvertimeRequest, request_id)
    if row is None or row.status != "PENDING":
        raise GovernanceError("Pending overtime request not found", "OVERTIME_NOT_PENDING")
    if approved_minutes < 0 or approved_minutes > row.requested_minutes:
        raise GovernanceError("Approved overtime must be within the requested minutes", "BAD_OVERTIME")
    row.approved_minutes = approved_minutes
    row.status = "APPROVED" if approved_minutes > 0 else "REJECTED"
    row.reviewed_by_user_id = reviewer_id
    row.reviewed_at = datetime.now(timezone.utc)
    db.flush()
    audit_event(
        db,
        actor_user_id=reviewer_id,
        action="REVIEW_OVERTIME",
        entity_type="OVERTIME_REQUEST",
        entity_id=row.id,
        new_value={"status": row.status, "approved_minutes": approved_minutes},
    )
    return row
