from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models import Device, Order, OrderLine, PickTask, Product, TaskStatus, User
from app.services.allocation import allocate_order
from app.services.picking import accept_task
from app.services.scheduling import active_task_for_actor, claim_next_task, reject_offer


def _new_task(db, ref: str, qty: int = 1, priority: int = 100):
    product = db.scalar(select(Product).where(Product.asin == "DEMO-AMBIENT-001"))
    order = Order(external_ref=ref, priority=priority)
    db.add(order)
    db.flush()
    db.add(OrderLine(order_id=order.id, product_id=product.id, requested_qty=qty))
    db.flush()
    task = allocate_order(db, order)
    db.commit()
    return order, task


def _actor(db):
    user = db.scalar(select(User).where(User.username == "picker1"))
    device = db.get(Device, "PDA-DEMO-001")
    return user, device


def test_claim_next_offer_is_resumable_after_restart(db):
    _, task = _new_task(db, "sched-resume")
    user, device = _actor(db)
    snap = claim_next_task(db, user.id, device.id)
    db.commit()
    assert snap["task_id"] == task.id
    assert snap["task_status"] == "OFFERED"
    assert snap["resumed"] is False
    assert snap["offer_expires_at"] is not None

    resumed = active_task_for_actor(db, user.id, device.id)
    assert resumed.id == task.id
    snap2 = claim_next_task(db, user.id, device.id)
    assert snap2["task_id"] == task.id
    assert snap2["resumed"] is True


def test_accept_then_claim_returns_same_active_task(db):
    _, task = _new_task(db, "sched-accepted")
    user, device = _actor(db)
    claim_next_task(db, user.id, device.id)
    db.flush()
    task = db.get(PickTask, task.id)
    accept_task(db, task, user.id, device.id)
    db.commit()

    snap = claim_next_task(db, user.id, device.id)
    assert snap["task_id"] == task.id
    assert snap["task_status"] == "ACCEPTED"
    assert snap["resumed"] is True


def test_reject_returns_offer_to_ready_queue(db):
    _, task = _new_task(db, "sched-reject")
    user, device = _actor(db)
    claim_next_task(db, user.id, device.id)
    db.flush()
    task = db.get(PickTask, task.id)
    result = reject_offer(db, task, user.id, device.id, "TOO_FAR")
    db.commit()
    assert result["status"] == "READY"
    task = db.get(PickTask, task.id)
    assert task.assigned_user_id is None
    assert task.assigned_device_id is None


def test_stale_offer_is_reclaimed(db):
    _, task1 = _new_task(db, "sched-stale-1", priority=1)
    _new_task(db, "sched-stale-2", priority=2)
    user, device = _actor(db)

    task1 = db.get(PickTask, task1.id)
    task1.status = TaskStatus.OFFERED.value
    task1.assigned_user_id = "gone-user"
    task1.assigned_device_id = "gone-device"
    task1.offered_at = datetime.now(timezone.utc) - timedelta(seconds=31)
    db.commit()

    snap = claim_next_task(db, user.id, device.id)
    db.commit()
    assert snap["task_id"] == task1.id
    assert snap["task_status"] == "OFFERED"
