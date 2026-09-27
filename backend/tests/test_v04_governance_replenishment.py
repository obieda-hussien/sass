from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models import Barcode, Device, EmployeeProfile, InventoryBalance, User
from app.models_ops import (
    AdminAuditEvent,
    BreakSession,
    ReplenishmentEvent,
    ReplenishmentTask,
    ShiftAssignment,
    PromotionRecord,
)
from app.seed import ensure_location
from app.services.governance import (
    GovernanceError,
    assign_shift,
    auto_clock_in,
    auto_clock_out,
    create_shift_template,
    effective_permissions,
    end_break,
    has_permission,
    set_user_permission,
    start_break,
)
from app.services.ops_platform import get_worker_state, set_worker_state
from app.services.workforce import ROLE_LEVELS, WorkforceError, promote_employee
from app.services.replenishment import (
    ReplenishmentError,
    claim,
    complete,
    confirm_item,
    scan_destination,
    scan_source,
)


def _user(db, username: str) -> User:
    return db.scalar(select(User).where(User.username == username))


def _product_barcode(db, asin: str) -> tuple[str, str]:
    from app.models import Product

    product = db.scalar(select(Product).where(Product.asin == asin))
    barcode = db.scalar(select(Barcode.code).where(Barcode.product_id == product.id))
    return product.id, barcode



def test_rank_ladder_promotion_is_audited_and_salary_change_is_explicit(db):
    with db.begin():
        picker = _user(db, "picker1")
        supervisor = _user(db, "supervisor")
        profile = db.get(EmployeeProfile, picker.id)
        if profile is None:
            profile = EmployeeProfile(
                user_id=picker.id,
                employee_code="PICKER-PROMO",
                full_name="Picker Promotion",
                base_salary_cents=500_000,
                overtime_rate_cents_per_hour=5_000,
                grace_minutes=10,
            )
            db.add(profile)
            db.flush()

        assert ROLE_LEVELS["PICKER"] < ROLE_LEVELS["SENIOR_PICKER"]
        first = promote_employee(
            db,
            user=picker,
            to_role="SENIOR_PICKER",
            reason="Consistent order quality and reliability",
            approver_id=supervisor.id,
            new_base_salary_cents=550_000,
        )
        assert picker.role == "SENIOR_PICKER"
        assert profile.base_salary_cents == 550_000
        assert first.from_role == "PICKER"
        assert first.to_role == "SENIOR_PICKER"

        second = promote_employee(
            db,
            user=picker,
            to_role="QUALITY",
            reason="Move into quality ownership",
            approver_id=supervisor.id,
        )
        assert picker.role == "QUALITY"
        assert profile.base_salary_cents == 550_000
        assert second.old_base_salary_cents == second.new_base_salary_cents == 550_000

        records = db.scalars(
            select(PromotionRecord)
            .where(PromotionRecord.user_id == picker.id)
            .order_by(PromotionRecord.created_at)
        ).all()
        assert [(row.from_role, row.to_role) for row in records] == [
            ("PICKER", "SENIOR_PICKER"),
            ("SENIOR_PICKER", "QUALITY"),
        ]

        with pytest.raises(WorkforceError) as downgrade:
            promote_employee(
                db,
                user=picker,
                to_role="PICKER",
                reason="Should not be accepted as promotion",
                approver_id=supervisor.id,
            )
        assert downgrade.value.code == "NOT_A_PROMOTION"

        with pytest.raises(WorkforceError) as admin:
            promote_employee(
                db,
                user=picker,
                to_role="ADMIN",
                reason="Admin cannot be reached through warehouse promotion",
                approver_id=supervisor.id,
            )
        assert admin.value.code == "ADMIN_PROMOTION_FORBIDDEN"


def test_permission_scope_can_extend_picker_without_changing_role(db):
    with db.begin():
        picker = _user(db, "picker1")
        supervisor = _user(db, "supervisor")

        assert picker.role == "PICKER"
        assert has_permission(db, picker, "replenishment.execute") is False

        set_user_permission(
            db,
            user_id=picker.id,
            permission="replenishment.execute",
            allowed=True,
            actor_user_id=supervisor.id,
        )
        assert has_permission(db, picker, "replenishment.execute") is True
        effective = effective_permissions(db, picker)
        assert "replenishment.execute" in effective["permissions"]

        audit = db.scalar(
            select(AdminAuditEvent)
            .where(AdminAuditEvent.entity_type == "USER_PERMISSION")
            .order_by(AdminAuditEvent.created_at.desc())
        )
        assert audit is not None
        assert audit.actor_user_id == supervisor.id


def test_overnight_shift_template_uses_local_timezone_and_auto_clock(db):
    with db.begin():
        picker = _user(db, "picker1")
        supervisor = _user(db, "supervisor")
        if db.get(EmployeeProfile, picker.id) is None:
            db.add(
                EmployeeProfile(
                    user_id=picker.id,
                    employee_code="PICKER1",
                    full_name="Picker One",
                    base_salary_cents=800_000,
                    overtime_rate_cents_per_hour=6_000,
                    grace_minutes=5,
                )
            )
            db.flush()

        template = create_shift_template(
            db,
            site_id="DEMO",
            name="Night",
            start_minute=22 * 60,
            end_minute=7 * 60,
            timezone_name="Africa/Cairo",
            break_minutes=30,
            grace_minutes=5,
            actor_user_id=supervisor.id,
        )
        assignment = assign_shift(
            db,
            user_id=picker.id,
            shift_template_id=template.id,
            shift_date=date(2026, 9, 28),
            actor_user_id=supervisor.id,
        )

        # Cairo is UTC+3 on this date. 22:00 local -> 19:00 UTC, 07:00 next day -> 04:00 UTC.
        assert assignment.scheduled_start_at.hour == 19
        assert assignment.scheduled_end_at.date() == date(2026, 9, 29)
        assert assignment.scheduled_end_at.hour == 4

        clock_in = datetime(2026, 9, 28, 19, 9, tzinfo=timezone.utc)
        result = auto_clock_in(db, user_id=picker.id, at=clock_in)
        assert result["late_minutes"] == 4
        assert get_worker_state(db, picker.id).state == "AVAILABLE"

        clock_out = datetime(2026, 9, 29, 4, 30, tzinfo=timezone.utc)
        closed = auto_clock_out(db, user_id=picker.id, at=clock_out)
        assert closed["overtime_minutes"] == 30
        assert get_worker_state(db, picker.id).state == "OFFLINE"

        assignment = db.get(ShiftAssignment, assignment.id)
        assert assignment.status == "COMPLETED"


def test_break_cannot_start_while_picker_has_active_order_lease(db):
    from app.models import Order, OrderLine
    from app.models_ops import ActivePickLease
    from app.services.allocation import allocate_order

    with db.begin():
        picker = _user(db, "picker1")
        product_id, _ = _product_barcode(db, "DEMO-AMBIENT-001")
        order = Order(external_ref="BREAK-GUARD")
        db.add(order)
        db.flush()
        db.add(OrderLine(order_id=order.id, product_id=product_id, requested_qty=1))
        db.flush()
        task = allocate_order(db, order)
        db.add(ActivePickLease(user_id=picker.id, task_id=task.id, device_id="PDA-DEMO-001"))

        with pytest.raises(GovernanceError) as error:
            start_break(db, user_id=picker.id)
        assert error.value.code == "ACTIVE_PICK_EXISTS"


def test_break_transitions_worker_state_and_records_duration(db):
    with db.begin():
        picker = _user(db, "picker1")
        set_worker_state(db, picker.id, "AVAILABLE", force=True)
        row = start_break(db, user_id=picker.id, break_type="REST", paid=True)
        assert get_worker_state(db, picker.id).state == "BREAK"
        assert row.ended_at is None

        row.started_at = datetime.now(timezone.utc) - timedelta(minutes=12)
        finished = end_break(db, user_id=picker.id)
        assert finished.duration_minutes >= 11
        assert get_worker_state(db, picker.id).state == "AVAILABLE"


def test_replenishment_requires_scan_chain_and_moves_inventory_once(db):
    with db.begin():
        supervisor = _user(db, "supervisor")
        worker = User(username="inventory1", password_hash="not-used", role="INVENTORY")
        db.add(worker)
        db.flush()
        set_worker_state(db, worker.id, "AVAILABLE", force=True)

        product_id, barcode = _product_barcode(db, "DEMO-AMBIENT-001")
        source = ensure_location(db, "P-1-A105A110")
        db.add(
            InventoryBalance(
                location_id=source.id,
                product_id=product_id,
                qty_on_hand=20,
                qty_reserved=0,
            )
        )
        db.flush()

        task = ReplenishmentTask(
            product_id=product_id,
            source_location_id=source.id,
            destination_location_id="P-1-A101A110",
            qty=8,
            status="READY",
            trigger="TEST",
            priority=90,
        )
        db.add(task)
        db.flush()

        claimed = claim(
            db,
            task=task,
            user_id=worker.id,
            device_id="PDA-DEMO-001",
        )
        assert claimed.status == "CLAIMED"
        assert get_worker_state(db, worker.id).state == "REPLENISHING"

        with pytest.raises(ReplenishmentError) as early_complete:
            complete(
                db,
                task=task,
                event_id="repl-too-early",
                user_id=worker.id,
                device_id="PDA-DEMO-001",
                actual_qty=8,
            )
        assert early_complete.value.code == "SCANS_INCOMPLETE"

        source_result = scan_source(
            db,
            task=task,
            event_id="repl-source-1",
            user_id=worker.id,
            device_id="PDA-DEMO-001",
            source_location_id=source.id,
        )
        assert source_result["duplicate"] is False

        item_result = confirm_item(
            db,
            task=task,
            event_id="repl-item-1",
            user_id=worker.id,
            device_id="PDA-DEMO-001",
            barcode=barcode,
        )
        assert item_result["duplicate"] is False

        destination_result = scan_destination(
            db,
            task=task,
            event_id="repl-dest-1",
            user_id=worker.id,
            device_id="PDA-DEMO-001",
            destination_location_id="P-1-A101A110",
        )
        assert destination_result["duplicate"] is False

        before_source = db.scalar(
            select(InventoryBalance).where(
                InventoryBalance.location_id == source.id,
                InventoryBalance.product_id == product_id,
            )
        ).qty_on_hand
        before_dest = db.scalar(
            select(InventoryBalance).where(
                InventoryBalance.location_id == "P-1-A101A110",
                InventoryBalance.product_id == product_id,
            )
        ).qty_on_hand

        result = complete(
            db,
            task=task,
            event_id="repl-complete-1",
            user_id=worker.id,
            device_id="PDA-DEMO-001",
            actual_qty=5,
        )
        assert result["duplicate"] is False
        assert result["task"]["status"] == "PARTIAL"
        assert result["remainder_task_id"] is not None
        assert get_worker_state(db, worker.id).state == "AVAILABLE"

        after_source = db.scalar(
            select(InventoryBalance).where(
                InventoryBalance.location_id == source.id,
                InventoryBalance.product_id == product_id,
            )
        ).qty_on_hand
        after_dest = db.scalar(
            select(InventoryBalance).where(
                InventoryBalance.location_id == "P-1-A101A110",
                InventoryBalance.product_id == product_id,
            )
        ).qty_on_hand
        assert before_source - after_source == 5
        assert after_dest - before_dest == 5

        events = db.scalars(
            select(ReplenishmentEvent).where(ReplenishmentEvent.replenishment_task_id == task.id)
        ).all()
        assert {event.event_type for event in events} >= {
            "CLAIM",
            "SOURCE_SCAN",
            "ITEM_SCAN",
            "DESTINATION_SCAN",
            "COMPLETE",
        }


def test_replenishment_rejects_wrong_source_and_wrong_item(db):
    with db.begin():
        worker = User(username="inventory2", password_hash="not-used", role="INVENTORY")
        db.add(worker)
        db.flush()
        set_worker_state(db, worker.id, "AVAILABLE", force=True)
        product_id, _ = _product_barcode(db, "DEMO-AMBIENT-001")
        task = ReplenishmentTask(
            product_id=product_id,
            source_location_id="P-1-A101A110",
            destination_location_id="P-1-A115E181",
            qty=1,
            status="READY",
        )
        db.add(task)
        db.flush()
        claim(db, task=task, user_id=worker.id, device_id="PDA-DEMO-001")

        with pytest.raises(ReplenishmentError) as wrong_source:
            scan_source(
                db,
                task=task,
                event_id="wrong-source",
                user_id=worker.id,
                device_id="PDA-DEMO-001",
                source_location_id="P-1-A115E181",
            )
        assert wrong_source.value.code == "SOURCE_LOCATION_MISMATCH"
