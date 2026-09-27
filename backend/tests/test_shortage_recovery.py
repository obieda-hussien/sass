from sqlalchemy import select

from app.models import Barcode, Device, InventoryBalance, Order, OrderLine, PickTaskItem, Product, User
from app.services.allocation import allocate_order
from app.services.picking import accept_task, cancel_order, recover_stow, recovery_snapshot, short_pick


def owned_task(db, asin="DEMO-AMBIENT-001", qty=2):
    product = db.scalar(select(Product).where(Product.asin == asin))
    user = db.scalar(select(User).where(User.username == "picker1"))
    device = db.get(Device, "PDA-DEMO-001")
    order = Order(external_ref=f"exception-{asin}-{qty}-{id(db)}")
    db.add(order)
    db.flush()
    db.add(OrderLine(order_id=order.id, product_id=product.id, requested_qty=qty))
    db.flush()
    task = allocate_order(db, order)
    task.assigned_user_id = user.id
    task.assigned_device_id = device.id
    task.status = "OFFERED"
    accept_task(db, task, user.id, device.id)
    db.commit()
    item = db.scalars(select(PickTaskItem).where(PickTaskItem.task_id == task.id)).first()
    db.commit()
    return order, task, item, product, user, device


def test_short_removes_phantom_stock_and_completes_line(db):
    order, task, item, product, user, device = owned_task(db, qty=2)
    before = db.scalar(select(InventoryBalance).where(
        InventoryBalance.location_id == item.source_location_id,
        InventoryBalance.product_id == product.id,
    ))
    before_qty = before.qty_on_hand
    before_reserved = before.qty_reserved

    ack = short_pick(
        db,
        task=task,
        event_id="short-1",
        client_seq=1,
        task_item_id=item.id,
        qty=1,
        reason="MISSING_AT_LOCATION",
        user_id=user.id,
        device_id=device.id,
    )
    db.commit()

    after = db.scalar(select(InventoryBalance).where(
        InventoryBalance.location_id == item.source_location_id,
        InventoryBalance.product_id == product.id,
    ))
    line = db.get(OrderLine, item.order_line_id)
    assert after.qty_on_hand == before_qty - 1
    assert after.qty_reserved == before_reserved - 1
    assert line.shorted_qty == 1
    assert ack.snapshot["shorted_units"] == 1
    assert ack.snapshot["processed_units"] == 1
    assert ack.snapshot["remaining_units"] == 1


def test_duplicate_short_is_idempotent(db):
    _, task, item, _, user, device = owned_task(db, qty=1)
    first = short_pick(
        db, task=task, event_id="short-dupe", client_seq=1,
        task_item_id=item.id, qty=1, reason="MISSING_AT_LOCATION",
        user_id=user.id, device_id=device.id,
    )
    db.commit()
    task = db.get(type(task), task.id)
    second = short_pick(
        db, task=task, event_id="short-dupe", client_seq=1,
        task_item_id=item.id, qty=1, reason="MISSING_AT_LOCATION",
        user_id=user.id, device_id=device.id,
    )
    db.commit()
    assert first.duplicate is False
    assert second.duplicate is True
    assert second.snapshot["shorted_units"] == 1


def test_cancelled_pick_can_be_recovered_to_compatible_storage(db):
    order, task, item, product, user, device = owned_task(db, qty=1)

    from app.services.picking import commit_pick
    commit_pick(
        db,
        task=task,
        event_id="pick-before-cancel",
        client_seq=1,
        task_item_id=item.id,
        location_id=item.source_location_id,
        product_id=product.id,
        qty=1,
        user_id=user.id,
        device_id=device.id,
    )
    db.commit()

    order = db.get(Order, order.id)
    cancelled = cancel_order(db, order, "CUSTOMER_CANCELLED")
    db.commit()
    assert cancelled["task_status"] == "RECOVERY_REQUIRED"

    task = db.get(type(task), task.id)
    recovery = recovery_snapshot(db, task)
    assert recovery["recovery_type"] == "PICK_TOTE_STOW"
    assert recovery["items"][0]["qty"] == 1
    assert item.source_location_id in recovery["items"][0]["compatible_destinations"]

    result = recover_stow(
        db,
        task=task,
        event_id="recovery-1",
        product_id=product.id,
        qty=1,
        destination_location_id=item.source_location_id,
        user_id=user.id,
        device_id=device.id,
    )
    db.commit()
    assert result["recovery_complete"] is True
    assert result["task_status"] == "CANCELLED"
    assert result["order_status"] == "CANCELLED"


def test_barcode_mapping_exists_for_demo_product(db):
    product = db.scalar(select(Product).where(Product.asin == "DEMO-AMBIENT-001"))
    barcode = db.scalar(select(Barcode).where(Barcode.product_id == product.id))
    assert barcode.code == "6220000000001"
