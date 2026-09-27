from sqlalchemy import select

from app.models import Device, InventoryBalance, Order, OrderLine, PickTaskItem, Product, User
from app.services.allocation import allocate_order
from app.services.fulfillment import complete_delivery, handoff_task, stage_task, start_pack_rack
from app.services.picking import accept_task, commit_pick


def test_pick_to_stage_to_handoff_to_delivery(db):
    product = db.scalar(select(Product).where(Product.asin == 'DEMO-AMBIENT-001'))
    user = db.scalar(select(User).where(User.username == 'picker1'))
    device = db.get(Device, 'PDA-DEMO-001')
    db.commit()

    order = Order(external_ref='full-flow')
    db.add(order); db.flush()
    db.add(OrderLine(order_id=order.id, product_id=product.id, requested_qty=2)); db.flush()
    task = allocate_order(db, order)
    task.assigned_user_id = user.id
    task.assigned_device_id = device.id
    task.status = 'OFFERED'
    accept_task(db, task, user.id, device.id)
    db.commit()

    item = db.scalars(select(PickTaskItem).where(PickTaskItem.task_id == task.id)).first()
    db.commit()
    commit_pick(
        db, task=task, event_id='full-pick', client_seq=1,
        task_item_id=item.id, location_id=item.source_location_id,
        product_id=product.id, qty=2, user_id=user.id, device_id=device.id,
    )
    db.commit()
    task = db.get(type(task), task.id)
    assert task.status == 'PICKED'

    start_pack_rack(db, task, user.id, device.id); db.commit()
    task = db.get(type(task), task.id)
    snap = stage_task(db, task, 'RACK-A-01', user.id, device.id); db.commit()
    assert snap['task_status'] == 'STAGED'

    task = db.get(type(task), task.id)
    snap = handoff_task(db, task, 'RIDER-DEMO', user.id, device.id); db.commit()
    assert snap['task_status'] == 'HANDED_OFF'

    task = db.get(type(task), task.id)
    snap = complete_delivery(db, task, user.id, device.id); db.commit()
    assert snap['task_status'] == 'COMPLETED'

    handoff_balance = db.scalar(select(InventoryBalance).where(
        InventoryBalance.location_id == 'HANDOFF:RIDER-DEMO',
        InventoryBalance.product_id == product.id,
    ))
    assert handoff_balance.qty_on_hand == 0
