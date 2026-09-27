from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    AttendanceEntry,
    EmployeeProfile,
    PasswordResetRequest,
    PayAdjustment,
    PerformanceEvent,
    PickTask,
    TaskStatus,
    User,
)
from ..security import hash_password

ALLOWED_ROLES = {"PICKER", "RECEIVER", "INVENTORY", "SUPERVISOR", "ADMIN"}
MANAGER_ROLES = {"SUPERVISOR", "ADMIN"}


class WorkforceError(RuntimeError):
    def __init__(self, message: str, code: str = "WORKFORCE_ERROR"):
        super().__init__(message)
        self.code = code


def normalize_role(role: str) -> str:
    value = role.strip().upper()
    if value not in ALLOWED_ROLES:
        raise WorkforceError(f"Unsupported role: {value}", "BAD_ROLE")
    return value


def employee_payload(db: Session, user: User, *, period: str | None = None) -> dict[str, Any]:
    profile = db.get(EmployeeProfile, user.id)
    payroll = payroll_preview(db, user.id, period) if profile else None
    return {
        "user_id": user.id,
        "username": user.username,
        "role": user.role,
        "active": user.active,
        "created_at": user.created_at.isoformat(),
        "profile": None if profile is None else {
            "employee_code": profile.employee_code,
            "full_name": profile.full_name,
            "email": profile.email,
            "phone": profile.phone,
            "address": profile.address,
            "job_title": profile.job_title,
            "department": profile.department,
            "hire_date": profile.hire_date.isoformat() if profile.hire_date else None,
            "employment_status": profile.employment_status,
            "currency": profile.currency,
            "base_salary_cents": profile.base_salary_cents,
            "overtime_rate_cents_per_hour": profile.overtime_rate_cents_per_hour,
            "scheduled_start_minutes": profile.scheduled_start_minutes,
            "grace_minutes": profile.grace_minutes,
            "notes": profile.notes,
            "updated_at": profile.updated_at.isoformat(),
        },
        "payroll": payroll,
    }


def create_employee(db: Session, payload: Any) -> tuple[User, str | None]:
    username = payload.username.strip()
    if db.scalar(select(User).where(func.lower(User.username) == username.lower())):
        raise WorkforceError("Username already exists", "USERNAME_EXISTS")
    if db.scalar(select(EmployeeProfile).where(EmployeeProfile.employee_code == payload.employee_code.strip())):
        raise WorkforceError("Employee code already exists", "EMPLOYEE_CODE_EXISTS")

    role = normalize_role(payload.role)
    password = payload.password or secrets.token_urlsafe(12)

    user = User(
        username=username,
        password_hash=hash_password(password),
        role=role,
        active=True,
    )
    db.add(user)
    db.flush()

    email = payload.email.strip().lower() if payload.email else None
    if email and db.scalar(select(EmployeeProfile).where(EmployeeProfile.email == email)):
        raise WorkforceError("Email already exists", "EMAIL_EXISTS")

    db.add(EmployeeProfile(
        user_id=user.id,
        employee_code=payload.employee_code.strip().upper(),
        full_name=payload.full_name.strip(),
        email=email,
        phone=payload.phone.strip() if payload.phone else None,
        address=payload.address.strip() if payload.address else None,
        job_title=payload.job_title.strip(),
        department=payload.department.strip(),
        hire_date=payload.hire_date,
        employment_status=payload.employment_status.strip().upper(),
        currency=payload.currency.strip().upper(),
        base_salary_cents=payload.base_salary_cents,
        overtime_rate_cents_per_hour=payload.overtime_rate_cents_per_hour,
        scheduled_start_minutes=payload.scheduled_start_minutes,
        grace_minutes=payload.grace_minutes,
        notes=payload.notes.strip() if payload.notes else None,
    ))
    db.flush()
    return user, None if payload.password else password


def update_employee(db: Session, user: User, payload: Any) -> None:
    profile = db.get(EmployeeProfile, user.id)
    if profile is None:
        raise WorkforceError("Employee profile not found", "PROFILE_NOT_FOUND")

    values = payload.model_dump(exclude_unset=True)
    if "role" in values and values["role"] is not None:
        user.role = normalize_role(values.pop("role"))
    if "active" in values and values["active"] is not None:
        user.active = bool(values.pop("active"))

    for field, value in values.items():
        if field in {"email", "phone", "address", "full_name", "job_title", "department", "employment_status", "currency", "notes"}:
            if isinstance(value, str):
                value = value.strip()
            if field == "email" and value:
                value = value.lower()
            if field in {"employment_status", "currency"} and value:
                value = value.upper()
        setattr(profile, field, value)
    db.flush()


def record_attendance(db: Session, user_id: str, payload: Any, approver_id: str) -> AttendanceEntry:
    profile = db.get(EmployeeProfile, user_id)
    if profile is None:
        raise WorkforceError("Employee profile not found", "PROFILE_NOT_FOUND")

    grace = timedelta(minutes=profile.grace_minutes)
    effective_late = payload.clock_in_at - payload.scheduled_start_at - grace
    late_minutes = max(0, int(effective_late.total_seconds() // 60))

    entry = AttendanceEntry(
        user_id=user_id,
        scheduled_start_at=payload.scheduled_start_at,
        clock_in_at=payload.clock_in_at,
        clock_out_at=payload.clock_out_at,
        late_minutes=late_minutes,
        overtime_minutes=payload.overtime_minutes,
        status=payload.status.strip().upper(),
        source="MANUAL",
        notes=payload.notes,
        approved_by_user_id=approver_id,
    )
    db.add(entry)
    db.flush()
    return entry


def record_performance(db: Session, user_id: str, payload: Any) -> PerformanceEvent:
    event = PerformanceEvent(
        user_id=user_id,
        event_type=payload.event_type.strip().upper(),
        order_id=payload.order_id,
        task_id=payload.task_id,
        minutes=payload.minutes,
        source=payload.source.strip().upper(),
        notes=payload.notes,
        occurred_at=payload.occurred_at or datetime.now(timezone.utc),
    )
    db.add(event)
    db.flush()
    return event


def add_pay_adjustment(db: Session, user_id: str, payload: Any, approver_id: str) -> PayAdjustment:
    adjustment = PayAdjustment(
        user_id=user_id,
        kind=payload.kind.strip().upper(),
        amount_cents=payload.amount_cents,
        reason=payload.reason.strip(),
        approved=payload.approved,
        approved_by_user_id=approver_id if payload.approved else None,
    )
    db.add(adjustment)
    db.flush()
    return adjustment


def period_bounds(period: str | None) -> tuple[str, datetime, datetime]:
    now = datetime.now(timezone.utc)
    if period:
        try:
            year, month = [int(part) for part in period.split("-", 1)]
            start = datetime(year, month, 1, tzinfo=timezone.utc)
        except Exception as exc:
            raise WorkforceError("Period must be YYYY-MM", "BAD_PERIOD") from exc
    else:
        start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)

    if start.month == 12:
        end = datetime(start.year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(start.year, start.month + 1, 1, tzinfo=timezone.utc)
    return f"{start.year:04d}-{start.month:02d}", start, end


def payroll_preview(db: Session, user_id: str, period: str | None = None) -> dict[str, Any]:
    profile = db.get(EmployeeProfile, user_id)
    if profile is None:
        raise WorkforceError("Employee profile not found", "PROFILE_NOT_FOUND")

    label, start, end = period_bounds(period)
    attendance = db.scalars(
        select(AttendanceEntry).where(
            AttendanceEntry.user_id == user_id,
            AttendanceEntry.scheduled_start_at >= start,
            AttendanceEntry.scheduled_start_at < end,
            AttendanceEntry.status == "APPROVED",
        )
    ).all()
    late_minutes = sum(item.late_minutes for item in attendance)
    overtime_minutes = sum(item.overtime_minutes for item in attendance)
    overtime_cents = (overtime_minutes * profile.overtime_rate_cents_per_hour + 30) // 60

    adjustments = db.scalars(
        select(PayAdjustment).where(
            PayAdjustment.user_id == user_id,
            PayAdjustment.created_at >= start,
            PayAdjustment.created_at < end,
            PayAdjustment.approved == True,  # noqa: E712
        )
    ).all()
    adjustment_cents = sum(item.amount_cents for item in adjustments)

    performance = db.scalars(
        select(PerformanceEvent).where(
            PerformanceEvent.user_id == user_id,
            PerformanceEvent.occurred_at >= start,
            PerformanceEvent.occurred_at < end,
        )
    ).all()
    by_type: dict[str, int] = {}
    for event in performance:
        by_type[event.event_type] = by_type.get(event.event_type, 0) + 1

    completed_orders = db.scalar(
        select(func.count()).select_from(PickTask).where(
            PickTask.assigned_user_id == user_id,
            PickTask.status == TaskStatus.COMPLETED.value,
            PickTask.finished_at >= start,
            PickTask.finished_at < end,
        )
    ) or 0

    return {
        "period": label,
        "currency": profile.currency,
        "base_salary_cents": profile.base_salary_cents,
        "overtime_minutes": overtime_minutes,
        "overtime_pay_cents": overtime_cents,
        "approved_adjustments_cents": adjustment_cents,
        "estimated_total_cents": profile.base_salary_cents + overtime_cents + adjustment_cents,
        "late_minutes": late_minutes,
        "completed_orders": int(completed_orders),
        "performance_events": by_type,
        "policy_note": (
            "Operational lateness and SLAM/order metrics are tracked for review only. "
            "They do not automatically reduce pay; only explicit approved adjustments affect payroll."
        ),
    }


def request_password_reset(db: Session, identifier: str) -> PasswordResetRequest | None:
    needle = identifier.strip().lower()
    user = db.scalar(select(User).where(func.lower(User.username) == needle))
    if user is None:
        profile = db.scalar(select(EmployeeProfile).where(func.lower(EmployeeProfile.email) == needle))
        user = db.get(User, profile.user_id) if profile else None
    if user is None:
        return None

    existing = db.scalar(
        select(PasswordResetRequest)
        .where(
            PasswordResetRequest.user_id == user.id,
            PasswordResetRequest.status == "PENDING",
        )
        .order_by(PasswordResetRequest.requested_at.desc())
    )
    if existing:
        return existing

    req = PasswordResetRequest(user_id=user.id)
    db.add(req)
    db.flush()
    return req


def issue_temporary_password(
    db: Session,
    reset: PasswordResetRequest,
    resolver_id: str,
    explicit_password: str | None = None,
) -> str:
    user = db.get(User, reset.user_id)
    if user is None:
        raise WorkforceError("User not found", "USER_NOT_FOUND")
    password = explicit_password or secrets.token_urlsafe(12)
    user.password_hash = hash_password(password)
    reset.status = "RESOLVED"
    reset.resolved_at = datetime.now(timezone.utc)
    reset.resolved_by_user_id = resolver_id
    db.flush()
    return password
