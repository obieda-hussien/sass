from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models import EmployeeProfile, InventoryBalance, Order, OrderLine, PickTaskItem, Product, User
from app.models_ops import InventoryAlert, ReplenishmentTask, StowTask
from app.services.allocation import allocate_order
from app.services.ops_platform import (
    OpsError,
    broadcast_task,
    claim_task,
    clock_in_shift,
    clock_out_shift,
    close_order_bag,
    complete_receiving,
    complete_stow_task,
    create_hold,
    create_shipment,
    direct_assign_task,
    get_worker_state,
    open_shipment_receiving,
    order_completion_summary,
    product_orderability,
    receive_shipment_line,
    search_orders,
    set_worker_state,
    shortage_side_effects,
)
from app.services.workforce import payroll_preview
from app.seed import ensure_location


def _user(db, username: str) -> User:
    return db.scalar(select(User).where(User.username == username))


def _product(db, asin: str) -> Product:
    return db.scalar(select(Product).where(Product.asin == asin))


def _make_order(db, product: Product, qty: int = 1):
    order = Order(external_ref=f"TEST-{product.asin}-{datetime.now(timezone.utc).timestamp()}")
    db.add(order)
    db.flush()
    db.add(OrderLine(order_id=order.id, product_id=product.id, requested_qty=qty))
    db.flush()
    return order, allocate_order(db, order)


def test_zone_hold_changes_fulfillable_not_physical_inventory(db):
    with db.begin():
        manager = _user(db, "supervisor")
        chilled = _product(db, "DEMO-CHILLED-001")
        before = db.scalar(
            select(InventoryBalance).where(
                InventoryBalance.product_id == chilled.id,
                InventoryBalance.location_id == "P-1-C124A110",
            )
        ).qty_on_hand

        create_hold(
            db,
            site_id="DEMO",
            scope_type="DOMAIN",
            scope_value="CHILLED",
            reason="TEMPERATURE_ISSUE",
            created_by_user_id=manager.id,
        )
        availability = product_orderability(db, chilled.id)
        after = db.scalar(
            select(InventoryBalance).where(
                InventoryBalance.product_id == chilled.id,
                InventoryBalance.location_id == "P-1-C124A110",
            )
        ).qty_on_hand

        assert before == after == 30
        assert availability["physical_stock"] == 30
        assert availability["fulfillable_stock"] == 0
        assert availability["blocked_stock"] == 30


def test_first_claim_wins_and_picker_cannot_hold_second_order(db):
    with db.begin():
        picker1 = _user(db, "picker1")
        picker2 = User(username="picker2", password_hash="not-used", role="PICKER")
        db.add(picker2)
        db.flush()
        set_worker_state(db, picker1.id, "AVAILABLE", force=True)
        set_worker_state(db, picker2.id, "AVAILABLE", force=True)

        product = _product(db, "DEMO-AMBIENT-001")
        _, task = _make_order(db, product, 1)
        offer = broadcast_task(db, task)
        assert offer["offered_to"] == 2

        won = claim_task(db, task, picker1.id, "PDA-DEMO-001")
        assert won.assigned_user_id == picker1.id

        with pytest.raises(OpsError) as losing:
            claim_task(db, task, picker2.id, "PDA-DEMO-001")
        assert losing.value.code == "ORDER_ALREADY_CLAIMED"

        _, task2 = _make_order(db, product, 1)
        broadcast_task(db, task2)
        with pytest.raises(OpsError) as second:
            claim_task(db, task2, picker1.id, "PDA-DEMO-001")
        assert second.value.code == "PICKER_NOT_ELIGIBLE"


def test_break_worker_cannot_receive_manual_assignment(db):
    with db.begin():
        picker = _user(db, "picker1")
        manager = _user(db, "supervisor")
        set_worker_state(db, picker.id, "BREAK", reason="REST")

        product = _product(db, "DEMO-AMBIENT-001")
        _, task = _make_order(db, product, 1)

        with pytest.raises(OpsError) as blocked:
            direct_assign_task(
                db,
                task,
                user_id=picker.id,
                manager_id=manager.id,
                device_id="PDA-DEMO-001",
            )
        assert blocked.value.code == "PICKER_NOT_ELIGIBLE"


def test_spoo_bags_are_searchable_and_summary_exposes_last_four(db):
    with db.begin():
        picker = _user(db, "picker1")
        set_worker_state(db, picker.id, "AVAILABLE", force=True)
        product = _product(db, "DEMO-AMBIENT-001")
        order, task = _make_order(db, product, 1)
        broadcast_task(db, task)
        claim_task(db, task, picker.id, "PDA-DEMO-001")

        close_order_bag(db, task, picker.id, "SPOO-12345678")
        close_order_bag(db, task, picker.id, "SPOO-87654321")

        summary = order_completion_summary(db, order.id)
        assert summary["bag_count"] == 2
        assert [bag["spoo_last4"] for bag in summary["bags"]] == ["5678", "4321"]

        by_spoo = search_orders(db, spoo="5678")
        assert [item["order_id"] for item in by_spoo] == [order.id]
        by_user = search_orders(db, username="picker1")
        assert order.id in {item["order_id"] for item in by_user}


def test_repeated_shortage_creates_count_alert_and_replenishment_candidate(db):
    with db.begin():
        picker = _user(db, "picker1")
        product = _product(db, "DEMO-AMBIENT-001")
        order, task = _make_order(db, product, 1)
        item = db.scalar(select(PickTaskItem).where(PickTaskItem.task_id == task.id))

        alt = ensure_location(db, "P-1-A105A110")
        db.add(InventoryBalance(location_id=alt.id, product_id=product.id, qty_on_hand=12, qty_reserved=0))
        db.flush()

        for idx in range(3):
            result = shortage_side_effects(
                db,
                event_id=f"short-evidence-{idx}",
                task=task,
                item=item,
                user_id=picker.id,
                exception_type="SHORT",
                reason="NOT_FOUND",
                qty=1,
            )

        alert = db.scalar(
            select(InventoryAlert).where(
                InventoryAlert.product_id == product.id,
                InventoryAlert.location_id == item.source_location_id,
                InventoryAlert.status == "OPEN",
            )
        )
        replenishment = db.scalar(
            select(ReplenishmentTask).where(
                ReplenishmentTask.product_id == product.id,
                ReplenishmentTask.destination_location_id == item.source_location_id,
            )
        )
        assert result["recent_short_count_30m"] == 3
        assert alert is not None
        assert replenishment is not None
        assert replenishment.source_location_id == alt.id


def test_receiving_and_stow_are_exclusive_operational_states(db):
    with db.begin():
        picker = _user(db, "picker1")
        chilled = _product(db, "DEMO-CHILLED-001")
        set_worker_state(db, picker.id, "AVAILABLE", force=True)

        shipment = create_shipment(
            db,
            label="SHIP-CHILL-001",
            shipment_type="VENDOR",
            storage_domain="CHILLED",
            lines=[{"product_id": chilled.id, "expected_qty": 4}],
            created_by_user_id=_user(db, "supervisor").id,
        )
        session = open_shipment_receiving(
            db,
            shipment=shipment,
            user_id=picker.id,
            device_id="PDA-DEMO-001",
        )
        assert get_worker_state(db, picker.id).state == "RECEIVING_CHILLED"

        receive_shipment_line(
            db,
            shipment=shipment,
            session=session,
            event_id="recv-1",
            product_id=chilled.id,
            good_qty=3,
            damaged_qty=1,
            lot_code="LOT-1",
            expires_on=(datetime.now(timezone.utc) + timedelta(days=7)).date(),
        )
        result = complete_receiving(db, shipment, session)
        assert result["missing_units"] == 0
        assert get_worker_state(db, picker.id).state == "STOWING"

        stow = db.scalar(select(StowTask).where(StowTask.shipment_id == shipment.id))
        completed = complete_stow_task(
            db,
            task=stow,
            destination_location_id="P-1-C124A110",
            user_id=picker.id,
            device_id="PDA-DEMO-001",
            event_id="stow-1",
        )
        assert completed["shipment_completed"] is True
        assert get_worker_state(db, picker.id).state == "AVAILABLE"


def test_shift_clock_calculates_late_overtime_and_payroll_inputs(db):
    with db.begin():
        picker = _user(db, "picker1")
        if db.get(EmployeeProfile, picker.id) is None:
            db.add(EmployeeProfile(
                user_id=picker.id,
                employee_code="PICKER1",
                full_name="Picker One",
                base_salary_cents=800_000,
                overtime_rate_cents_per_hour=6_000,
                grace_minutes=5,
            ))
            db.flush()

        start = datetime(2026, 9, 27, 14, 0, tzinfo=timezone.utc)
        end = datetime(2026, 9, 27, 23, 0, tzinfo=timezone.utc)
        shift = clock_in_shift(
            db,
            user_id=picker.id,
            scheduled_start_at=start,
            scheduled_end_at=end,
            clock_in_at=start + timedelta(minutes=15),
        )
        assert shift.late_minutes == 10

        closed = clock_out_shift(
            db,
            user_id=picker.id,
            clock_out_at=end + timedelta(minutes=30),
        )
        assert closed.overtime_minutes == 30
        assert closed.early_leave_minutes == 0
        assert closed.worked_minutes == 555

        payroll = payroll_preview(db, picker.id, "2026-09")
        assert payroll["late_minutes"] == 10
        assert payroll["overtime_minutes"] == 30
        assert payroll["worked_minutes"] == 555
