from sqlalchemy import select

from app.models import Device, Order, OrderLine, PickTaskItem, Product, User
from app.services.allocation import allocate_order
from app.services.fulfillment import complete_delivery, handoff_task, stage_task, start_pack_rack
from app.services.picking import accept_task, commit_pick


def owned_picked_task(db):
    product = db.scalar(select(Product).where(Product.asin == "DEMO-AMBIENT-001"))
    user = db.scalar(select(User).where(User.username == "picker1"))
    device = db.get(Device, "PDA-DEMO-001")
    order = Order(external_ref=f"retry-safe-{id(db)}")
    db.add(order)
    db.flush()
    db.add(OrderLine(order_id=order.id, product_id=product.id, requested_qty=1))
    db.flush()
    task = allocate_order(db, order)
    task.assigned_user_id = user.id
    task.assigned_device_id = device.id
    task.status = "OFFERED"
    first_accept = accept_task(db, task, user.id, device.id)
    second_accept = accept_task(db, task, user.id, device.id)
    assert first_accept["task_id"] == second_accept["task_id"]

    item = db.scalars(select(PickTaskItem).where(PickTaskItem.task_id == task.id)).first()
    commit_pick(
        db,
        task=task,
        event_id="retry-safe-pick",
        client_seq=1,
        task_item_id=item.id,
        location_id=item.source_location_id,
        product_id=product.id,
        qty=1,
        user_id=user.id,
        device_id=device.id,
    )
    db.commit()
    return order, task, user, device


def test_fulfillment_retries_do_not_duplicate_inventory_moves(db):
    _, task, user, device = owned_picked_task(db)

    first_pack = start_pack_rack(db, task, user.id, device.id)
    second_pack = start_pack_rack(db, task, user.id, device.id)
    assert first_pack["task_status"] == "PACK_RACK"
    assert second_pack["task_status"] == "PACK_RACK"

    first_stage = stage_task(db, task, "RACK-01", user.id, device.id)
    second_stage = stage_task(db, task, "RACK-01", user.id, device.id)
    assert first_stage["task_status"] == "STAGED"
    assert second_stage["task_status"] == "STAGED"

    first_handoff = handoff_task(db, task, "RIDER-01", user.id, device.id)
    second_handoff = handoff_task(db, task, "RIDER-01", user.id, device.id)
    assert first_handoff["task_status"] == "HANDED_OFF"
    assert second_handoff["task_status"] == "HANDED_OFF"

    first_complete = complete_delivery(db, task, user.id, device.id)
    second_complete = complete_delivery(db, task, user.id, device.id)
    assert first_complete["task_status"] == "COMPLETED"
    assert second_complete["task_status"] == "COMPLETED"
