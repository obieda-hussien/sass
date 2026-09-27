from datetime import datetime, timedelta, timezone
from sqlalchemy import select

from app.models import Barcode, Device, DowntimeSegment, Order, OrderLine, PickTaskItem, Product, User
from app.services.allocation import allocate_order
from app.services.picking import accept_task, cancel_order, commit_pick, PickError, task_snapshot
from app.services.sla import board_target_seconds, effective_elapsed_seconds


def create_order_and_task(db, asin="DEMO-AMBIENT-001", qty=3):
    product = db.scalar(select(Product).where(Product.asin == asin))
    db.commit()
    order = Order(external_ref=f"test-{asin}-{qty}-{id(db)}")
    db.add(order)
    db.flush()
    db.add(OrderLine(order_id=order.id, product_id=product.id, requested_qty=qty))
    db.flush()
    task = allocate_order(db, order)
    db.commit()
    return order, task, product


def prepare_owned_task(db, task):
    user = db.scalar(select(User).where(User.username == "picker1"))
    device = db.get(Device, "PDA-DEMO-001")
    db.commit()
    task = db.get(type(task), task.id)
    task.assigned_user_id = user.id
    task.assigned_device_id = device.id
    task.status = "OFFERED"
    accept_task(db, task, user.id, device.id)
    db.commit()
    return user, device, task


def test_duplicate_scan_never_double_counts(db):
    order, task, product = create_order_and_task(db, qty=2)
    user, device, task = prepare_owned_task(db, task)
    item = db.scalars(select(PickTaskItem).where(PickTaskItem.task_id == task.id)).first()
    db.commit()

    ack1 = commit_pick(
        db, task=task, event_id="scan-1", client_seq=1, task_item_id=item.id,
        location_id=item.source_location_id, product_id=product.id, qty=1,
        user_id=user.id, device_id=device.id,
    )
    db.commit()
    task = db.get(type(task), task.id)
    ack2 = commit_pick(
        db, task=task, event_id="scan-1", client_seq=1, task_item_id=item.id,
        location_id=item.source_location_id, product_id=product.id, qty=1,
        user_id=user.id, device_id=device.id,
    )
    db.commit()
    assert ack1.duplicate is False
    assert ack2.duplicate is True
    assert ack2.snapshot["picked_units"] == 1


def test_out_of_order_scan_forces_reconciliation(db):
    _, task, product = create_order_and_task(db, qty=2)
    user, device, task = prepare_owned_task(db, task)
    item = db.scalars(select(PickTaskItem).where(PickTaskItem.task_id == task.id)).first()
    db.commit()
    try:
        commit_pick(
            db, task=task, event_id="scan-2", client_seq=2, task_item_id=item.id,
            location_id=item.source_location_id, product_id=product.id, qty=1,
            user_id=user.id, device_id=device.id,
        )
        assert False, "expected conflict"
    except PickError as e:
        db.rollback()
        assert e.code == "SEQUENCE_CONFLICT"


def test_wrong_barcode_is_rejected_before_inventory_move(db):
    _, task, product = create_order_and_task(db, qty=2)
    user, device, task = prepare_owned_task(db, task)
    item = db.scalars(select(PickTaskItem).where(PickTaskItem.task_id == task.id)).first()
    other = db.scalar(select(Product).where(Product.asin == "DEMO-CHIPS-001"))
    wrong_barcode = db.scalar(select(Barcode.code).where(Barcode.product_id == other.id))
    db.commit()

    try:
        commit_pick(
            db, task=task, event_id="wrong-barcode", client_seq=1, task_item_id=item.id,
            location_id=item.source_location_id, product_id=product.id, qty=1,
            barcode=wrong_barcode, user_id=user.id, device_id=device.id,
        )
        assert False, "expected barcode mismatch"
    except PickError as e:
        db.rollback()
        assert e.code == "BARCODE_MISMATCH"

    task = db.get(type(task), task.id)
    assert task.client_high_water_seq == 0
    item = db.get(PickTaskItem, item.id)
    assert item.picked_qty == 0


def test_task_snapshot_contains_picker_catalog_metadata(db):
    _, task, product = create_order_and_task(db, qty=1)
    snap = task_snapshot(db, task)
    item = snap["items"][0]
    assert item["asin"] == product.asin
    assert item["title"]
    assert item["barcodes"] == ["6220000000001"]


def test_mid_pick_cancel_becomes_recovery_not_disappearance(db):
    order, task, product = create_order_and_task(db, qty=2)
    user, device, task = prepare_owned_task(db, task)
    item = db.scalars(select(PickTaskItem).where(PickTaskItem.task_id == task.id)).first()
    db.commit()
    commit_pick(
        db, task=task, event_id="scan-cancel", client_seq=1, task_item_id=item.id,
        location_id=item.source_location_id, product_id=product.id, qty=1,
        user_id=user.id, device_id=device.id,
    )
    db.commit()
    order = db.get(Order, order.id)
    snap = cancel_order(db, order, "CUSTOMER_CANCELLED")
    db.commit()
    assert snap["task_status"] == "RECOVERY_REQUIRED"
    assert snap["recovery_required"] is True
    assert snap["picked_units"] == 1


def test_sla_excludes_system_downtime(db):
    _, task, _ = create_order_and_task(db, qty=4)
    now = datetime.now(timezone.utc)
    task = db.get(type(task), task.id)
    task.started_at = now - timedelta(minutes=5)
    db.add(DowntimeSegment(
        task_id=task.id, kind="NETWORK_OFFLINE", source="DEVICE",
        started_at=now - timedelta(minutes=4), ended_at=now - timedelta(minutes=2),
    ))
    db.commit()
    task = db.get(type(task), task.id)
    assert 175 <= effective_elapsed_seconds(db, task, now) <= 185
    assert board_target_seconds(4) == 180
    assert board_target_seconds(24) == 960


def test_cancel_releases_unpicked_reservations(db):
    order, task, product = create_order_and_task(db, qty=3)
    item = db.scalars(select(PickTaskItem).where(PickTaskItem.task_id == task.id)).first()
    bal = db.scalar(select(__import__('app.models', fromlist=['InventoryBalance']).InventoryBalance).where(
        __import__('app.models', fromlist=['InventoryBalance']).InventoryBalance.location_id == item.source_location_id,
        __import__('app.models', fromlist=['InventoryBalance']).InventoryBalance.product_id == product.id,
    ))
    assert bal.qty_reserved == 3
    db.commit()
    order = db.get(Order, order.id)
    cancel_order(db, order, "NO_LONGER_NEEDED")
    db.commit()
    bal = db.scalar(select(__import__('app.models', fromlist=['InventoryBalance']).InventoryBalance).where(
        __import__('app.models', fromlist=['InventoryBalance']).InventoryBalance.location_id == item.source_location_id,
        __import__('app.models', fromlist=['InventoryBalance']).InventoryBalance.product_id == product.id,
    ))
    assert bal.qty_reserved == 0
