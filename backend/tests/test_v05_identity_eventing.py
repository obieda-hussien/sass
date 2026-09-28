from sqlalchemy import select
import pytest

from app.models import EmployeeProfile, User
from app.models_ops import OutboxEvent
from app.schemas import EmployeeCreateRequest
from app.security import verify_password
from app.services.governance import audit_event
from app.services.ops_platform import set_worker_state
from app.services.workforce import (
    WorkforceError,
    create_employee,
    generate_numeric_pin,
    set_employee_pin,
    soft_delete_employee,
    update_username,
)


def test_numeric_pin_policy_and_first_login_flag(db):
    pin = generate_numeric_pin()
    assert pin.isdigit()
    assert len(pin) == 6

    with db.begin():
        employee, temporary = create_employee(
            db,
            EmployeeCreateRequest(
                username="pinpicker",
                employee_code="PIN-001",
                full_name="PIN Picker",
                role="PICKER",
            ),
        )
        assert employee.must_change_password is True
        assert temporary.isdigit()
        assert len(temporary) == 6
        assert verify_password(temporary, employee.password_hash)

        explicit = "8" * 8
        result = set_employee_pin(
            db,
            employee,
            pin=explicit,
            require_change_on_next_login=True,
        )
        assert result == explicit
        assert employee.must_change_password is True
        assert verify_password(explicit, employee.password_hash)


def test_username_is_unique_case_insensitively_and_soft_delete_preserves_identity(db):
    with db.begin():
        first, _ = create_employee(
            db,
            EmployeeCreateRequest(
                username="warehouse.one",
                employee_code="USR-001",
                full_name="Warehouse One",
            ),
        )
        second, _ = create_employee(
            db,
            EmployeeCreateRequest(
                username="warehouse.two",
                employee_code="USR-002",
                full_name="Warehouse Two",
            ),
        )

        with pytest.raises(WorkforceError) as duplicate:
            update_username(db, second, "WAREHOUSE.ONE")
        assert duplicate.value.code == "USERNAME_EXISTS"

        old, new = update_username(db, second, "warehouse.renamed")
        assert old == "warehouse.two"
        assert new == "warehouse.renamed"

        profile_id = second.id
        soft_delete_employee(db, second, reason="Employment ended")
        assert second.active is False
        assert second.deleted_at is not None
        assert db.get(EmployeeProfile, profile_id) is not None


def test_audit_and_worker_state_events_create_transactional_outbox(db):
    with db.begin():
        supervisor = db.scalar(select(User).where(User.username == "supervisor"))
        picker = db.scalar(select(User).where(User.username == "picker1"))

        audit_event(
            db,
            actor_user_id=supervisor.id,
            action="TEST_SENSITIVE_CHANGE",
            entity_type="USER",
            entity_id=picker.id,
            reason="v0.5 audit coverage test",
        )
        set_worker_state(
            db,
            picker.id,
            "BREAK",
            reason="TEST_BREAK",
            force=True,
        )

        topics = set(db.scalars(select(OutboxEvent.topic)).all())
        assert "audit.admin" in topics
        assert "worker.state.changed" in topics
