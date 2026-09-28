from sqlalchemy import select
import pytest

from app.models import InventoryBalance, Order, OrderLine, PickTask, Product, User, Device
from app.models_ops import OrderBag
from app.services.operations import (
    OperationError, active_unpack, apply_cycle_count, bind_unpack_source, boh_move, complete_unpack, damage_move,
    record_cycle_count, scan_unpack, start_cycle_count, start_unpack, unpack_summary,
)


def actor(db):
    user = db.scalar(select(User).where(User.username == "picker1"))
    device = db.get(Device, "PDA-DEMO-001")
    db.commit()
    return user, device


def product(db, asin):
    p = db.scalar(select(Product).where(Product.asin == asin))
    db.commit()
    return p


def test_unpack_enforces_temperature_and_boh_compatibility(db):
    user, device = actor(db)
    chilled = product(db, "DEMO-CHILLED-001")
    session = start_unpack(
        db,
        "CHILLED",
        user.id,
        device.id,
        source_ref="TEST-BAG-CHILLED",
        expected_items=[{"product_id": chilled.id, "expected_qty": 2}],
    )
    db.commit()
    session = db.get(type(session), session.id)
    result = scan_unpack(db, session, "unpack-1", chilled.id, 2)
    db.commit()
    assert result["tote_location_id"] == "TSCRETCHL01"

    summary = complete_unpack(db, session)
    db.commit()
    assert summary["status"] == "COMPLETED"
    assert "P-1-C124A110" in summary["items"][0]["compatible_destinations"]

    move = boh_move(
        db, event_id="boh-1", product_id=chilled.id, qty=2,
        source_location_id="TSCRETCHL01", destination_location_id="P-1-C124A110",
        user_id=user.id, device_id=device.id,
    )
    db.commit()
    assert move["destination_qty"] >= 2


def test_unpack_rejects_unexpected_item_and_incomplete_close(db):
    user, device = actor(db)
    ambient = product(db, "DEMO-AMBIENT-001")
    frozen = product(db, "DEMO-FROZEN-001")
    session = start_unpack(
        db,
        "AMBIENT",
        user.id,
        device.id,
        source_ref="TEST-BAG-AMBIENT",
        expected_items=[{"product_id": ambient.id, "expected_qty": 2}],
    )
    db.commit()
    session = db.get(type(session), session.id)

    try:
        scan_unpack(db, session, "wrong-item", frozen.id, 1)
        assert False, "expected unexpected-item rejection"
    except OperationError as e:
        db.rollback()
        assert e.code == "UNEXPECTED_UNPACK_ITEM"

    session = db.get(type(session), session.id)
    scan_unpack(db, session, "ambient-1", ambient.id, 1)
    db.commit()
    session = db.get(type(session), session.id)
    try:
        complete_unpack(db, session)
        assert False, "expected incomplete manifest rejection"
    except OperationError as e:
        db.rollback()
        assert e.code == "UNPACK_INCOMPLETE"

    session = db.get(type(session), session.id)
    scan_unpack(db, session, "ambient-2", ambient.id, 1)
    db.commit()
    session = db.get(type(session), session.id)
    summary = complete_unpack(db, session)
    db.commit()
    assert summary["status"] == "COMPLETED"
    assert summary["verified_units"] == 2
    assert summary["remaining_units"] == 0


def test_damage_moves_inventory_out_of_sellable_location(db):
    user, device = actor(db)
    ambient = product(db, "DEMO-AMBIENT-001")
    before = db.scalar(select(InventoryBalance).where(
        InventoryBalance.product_id == ambient.id,
        InventoryBalance.location_id == "P-1-A101A110",
    )).qty_on_hand
    db.commit()
    result = damage_move(
        db, event_id="dmg-1", product_id=ambient.id, qty=1,
        source_location_id="P-1-A101A110", reason="OPEN_PACKAGE",
        user_id=user.id, device_id=device.id,
    )
    db.commit()
    assert result["damage_qty"] == 1
    after = db.scalar(select(InventoryBalance).where(
        InventoryBalance.product_id == ambient.id,
        InventoryBalance.location_id == "P-1-A101A110",
    )).qty_on_hand
    assert after == before - 1


def test_cycle_count_adjustment_is_auditable_inventory_movement(db):
    user, device = actor(db)
    ambient = product(db, "DEMO-AMBIENT-001")
    session = start_cycle_count(db, "P-1-A101A110", user.id)
    db.commit()
    session = db.get(type(session), session.id)
    bal = db.scalar(select(InventoryBalance).where(
        InventoryBalance.product_id == ambient.id,
        InventoryBalance.location_id == "P-1-A101A110",
    ))
    counted = bal.qty_on_hand - 2
    db.commit()
    entry = record_cycle_count(db, session, ambient.id, counted)
    db.commit()
    assert entry.variance == -2
    session = db.get(type(session), session.id)
    result = apply_cycle_count(db, session, "COUNT_VERIFIED", user.id, device.id)
    db.commit()
    assert result["status"] == "COMPLETED"
    bal = db.scalar(select(InventoryBalance).where(
        InventoryBalance.product_id == ambient.id,
        InventoryBalance.location_id == "P-1-A101A110",
    ))
    assert bal.qty_on_hand == counted



def test_unpack_start_is_retry_safe_and_resumable(db):
    user, device = actor(db)
    ambient = product(db, "DEMO-AMBIENT-001")
    first = start_unpack(
        db,
        "AMBIENT",
        user.id,
        device.id,
        source_ref="TEST-RESUME-BAG",
        expected_items=[{"product_id": ambient.id, "expected_qty": 1}],
    )
    db.commit()
    first_id = first.id

    second = start_unpack(db, "ambient", user.id, device.id)
    db.commit()
    assert second.id == first_id

    resumed = active_unpack(db, user.id, device.id, "AMBIENT")
    assert resumed is not None
    assert resumed.id == first_id
    assert resumed.tote_location_id == "TSCRET001"

    scan_unpack(db, resumed, "resume-item", ambient.id, 1)
    db.commit()
    resumed = db.get(type(resumed), resumed.id)
    complete_unpack(db, resumed)
    db.commit()
    third = start_unpack(db, "AMBIENT", user.id, device.id)
    db.commit()
    assert third.id != first_id



def test_unpack_can_bind_single_bag_spoo_manifest(db):
    user, device = actor(db)
    ambient = product(db, "DEMO-AMBIENT-001")

    order = Order(external_ref="RETURN-MANIFEST-001", status="COMPLETED")
    db.add(order)
    db.flush()
    db.add(OrderLine(
        order_id=order.id,
        product_id=ambient.id,
        requested_qty=2,
        allocated_qty=2,
        picked_qty=2,
        shorted_qty=0,
    ))
    task = PickTask(order_id=order.id, status="COMPLETED", expected_units=2)
    db.add(task)
    db.flush()
    db.add(OrderBag(
        order_id=order.id,
        task_id=task.id,
        bag_no=1,
        spoo_code="SPOO-RETURN-0001",
        closed_by_user_id=user.id,
    ))
    db.commit()

    session = start_unpack(db, "AMBIENT", user.id, device.id)
    db.commit()
    session = db.get(type(session), session.id)

    bind_unpack_source(db, session, "SPOO-RETURN-0001")
    db.commit()
    session = db.get(type(session), session.id)
    summary = unpack_summary(db, session)
    assert summary["manifest_locked"] is True
    assert summary["expected_units"] == 2
    assert summary["remaining_units"] == 2

    scan_unpack(db, session, "return-scan-1", ambient.id, 1)
    scan_unpack(db, session, "return-scan-2", ambient.id, 1)
    db.commit()
    summary = unpack_summary(db, session)
    assert summary["complete_ready"] is True
    assert summary["verified_units"] == 2


def test_one_spoo_covers_all_order_bags_and_completed_order_cannot_reopen(db):
    user, device = actor(db)
    ambient = product(db, "DEMO-AMBIENT-001")
    order = Order(external_ref="MULTI-BAG-RETURN", status="COMPLETED")
    db.add(order)
    db.flush()
    db.add(OrderLine(order_id=order.id, product_id=ambient.id, requested_qty=3,
                     allocated_qty=3, picked_qty=3, shorted_qty=0))
    task = PickTask(order_id=order.id, status="COMPLETED", expected_units=3)
    db.add(task)
    db.flush()
    for number in (1, 2):
        db.add(OrderBag(order_id=order.id, task_id=task.id, bag_no=number,
                        spoo_code=f"SPOO-MULTI-{number}", closed_by_user_id=user.id))
    db.commit()

    session = start_unpack(db, "AMBIENT", user.id, device.id)
    bind_unpack_source(db, session, "SPOO-MULTI-1")
    bind_unpack_source(db, session, "SPOO-MULTI-2")
    assert unpack_summary(db, session)["expected_units"] == 3
    scan_unpack(db, session, "multi-return-1", ambient.id, 3)
    assert complete_unpack(db, session)["status"] == "COMPLETED"
    db.commit()

    second = start_unpack(db, "AMBIENT", user.id, device.id)
    with pytest.raises(OperationError) as error:
        bind_unpack_source(db, second, "SPOO-MULTI-2")
    assert error.value.code == "ORDER_ALREADY_UNPACKED"
