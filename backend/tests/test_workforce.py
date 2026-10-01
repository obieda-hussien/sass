from datetime import datetime, timezone

from app.models import User
from app.schemas import (
    AttendanceCreateRequest,
    EmployeeCreateRequest,
    PayAdjustmentCreateRequest,
    PerformanceEventCreateRequest,
)
from app.security import hash_password, verify_password
from app.services.workforce import (
    add_pay_adjustment,
    create_employee,
    issue_temporary_password,
    payroll_preview,
    record_attendance,
    record_performance,
    request_password_reset,
)


def test_employee_payroll_and_password_recovery(db):
    manager = User(
        username="manager",
        password_hash=hash_password("ManagerPass123!"),
        role="SUPERVISOR",
        active=True,
    )
    db.add(manager)
    db.commit()

    req = EmployeeCreateRequest(
        username="newpicker",
        employee_code="EMP-1001",
        full_name="New Picker",
        email="picker@example.com",
        phone="+201000000000",
        address="Alexandria",
        job_title="Picker",
        department="Operations",
        base_salary_cents=100_000,
        overtime_rate_cents_per_hour=6_000,
        grace_minutes=10,
    )
    with db.begin():
        employee, generated = create_employee(db, req)
    assert generated
    assert generated.isdigit()
    assert len(generated) == 6
    assert verify_password(generated, employee.password_hash)

    attendance = AttendanceCreateRequest(
        scheduled_start_at=datetime(2026, 9, 10, 9, 0, tzinfo=timezone.utc),
        clock_in_at=datetime(2026, 9, 10, 9, 17, tzinfo=timezone.utc),
        clock_out_at=datetime(2026, 9, 10, 19, 0, tzinfo=timezone.utc),
        overtime_minutes=90,
        status="APPROVED",
    )
    with db.begin():
        entry = record_attendance(db, employee.id, attendance, manager.id)
    assert entry.late_minutes == 7

    with db.begin():
        record_performance(
            db,
            employee.id,
            PerformanceEventCreateRequest(
                event_type="LATE_SLAM",
                minutes=4,
                notes="Recorded for supervisor review",
                occurred_at=datetime(2026, 9, 10, 18, 0, tzinfo=timezone.utc),
            ),
        )
        adjustment = add_pay_adjustment(
            db,
            employee.id,
            PayAdjustmentCreateRequest(
                kind="MANUAL_ADJUSTMENT",
                amount_cents=-500,
                reason="Approved payroll correction",
                approved=True,
            ),
            manager.id,
        )
        # This historical payroll fixture must not depend on the month CI runs.
        adjustment.created_at = datetime(2026, 9, 10, 18, 0, tzinfo=timezone.utc)

    preview = payroll_preview(db, employee.id, "2026-09")
    assert preview["late_minutes"] == 7
    assert preview["overtime_minutes"] == 90
    assert preview["overtime_pay_cents"] == 9_000
    assert preview["performance_events"]["LATE_SLAM"] == 1
    assert preview["estimated_total_cents"] == 108_500
    assert "do not automatically reduce pay" in preview["policy_note"]
    db.commit()

    with db.begin():
        reset = request_password_reset(db, "picker@example.com")
    assert reset is not None

    explicit_pin = "7" * 6
    with db.begin():
        temporary = issue_temporary_password(db, reset, manager.id, explicit_pin)
    assert temporary == explicit_pin
    assert verify_password(explicit_pin, employee.password_hash)
    assert reset.status == "RESOLVED"
