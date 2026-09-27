from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import InventoryBalance, Location, Order, OrderStatus, PickTask, TaskStatus
from .inventory import move_inventory
from .operations import audit
from .ops_platform import release_pick_lease
from .picking import ensure_virtual_location, task_snapshot


class FulfillmentError(Exception):
    def __init__(self, message: str, code: str = "FULFILLMENT_ERROR"):
        super().__init__(message)
        self.code = code


def start_pack_rack(db: Session, task: PickTask, user_id: str, device_id: str) -> dict:
    if task.status == TaskStatus.PACK_RACK.value:
        return task_snapshot(db, task)
    if task.status != TaskStatus.PICKED.value:
        raise FulfillmentError(f"Task must be PICKED, got {task.status}", "INVALID_STATE")
    order = db.get(Order, task.order_id)
    task.status = TaskStatus.PACK_RACK.value
    order.status = OrderStatus.PACK_RACK.value
    task.server_version += 1
    audit(db, "PACK_RACK_STARTED", "PICK_TASK", task.id, user_id=user_id, device_id=device_id)
    db.flush()
    return task_snapshot(db, task)


def stage_task(db: Session, task: PickTask, stage_location_id: str, user_id: str, device_id: str) -> dict:
    stage = f"STAGE:{stage_location_id.strip().upper()}"
    if task.status == TaskStatus.STAGED.value:
        if task.stage_location_id == stage:
            return task_snapshot(db, task)
        raise FulfillmentError("Task is already staged at another location", "STAGE_MISMATCH")
    if task.status not in {TaskStatus.PICKED.value, TaskStatus.PACK_RACK.value}:
        raise FulfillmentError(f"Task cannot be staged from {task.status}", "INVALID_STATE")
    order = db.get(Order, task.order_id)
    source = f"PICKTOTE:{order.id}"
    ensure_virtual_location(db, stage)

    balances = db.scalars(select(InventoryBalance).where(
        InventoryBalance.location_id == source,
        InventoryBalance.qty_on_hand > 0,
    )).all()
    if not balances:
        raise FulfillmentError("Pick tote contains no inventory", "EMPTY_PICK_TOTE")
    for bal in balances:
        move_inventory(
            db,
            event_id=f"stage:{task.id}:{bal.product_id}:{task.server_version}",
            product_id=bal.product_id,
            qty=bal.qty_on_hand,
            source_location_id=source,
            destination_location_id=stage,
            reason="STAGE",
            order_id=order.id,
            task_id=task.id,
            user_id=user_id,
            device_id=device_id,
        )
    task.stage_location_id = stage
    task.status = TaskStatus.STAGED.value
    order.status = OrderStatus.STAGED.value
    task.server_version += 1
    audit(db, "ORDER_STAGED", "PICK_TASK", task.id, user_id=user_id, device_id=device_id, payload={"stage": stage})
    db.flush()
    return task_snapshot(db, task)


def handoff_task(db: Session, task: PickTask, handoff_ref: str, user_id: str, device_id: str) -> dict:
    normalized_handoff = handoff_ref.strip().upper()
    if task.status == TaskStatus.HANDED_OFF.value:
        if (task.handoff_ref or "").strip().upper() == normalized_handoff:
            return task_snapshot(db, task)
        raise FulfillmentError("Task was handed off to another reference", "HANDOFF_MISMATCH")
    if task.status not in {TaskStatus.STAGED.value, TaskStatus.HANDOFF_READY.value}:
        raise FulfillmentError(f"Task cannot hand off from {task.status}", "INVALID_STATE")
    if not task.stage_location_id:
        raise FulfillmentError("Task has no stage location", "MISSING_STAGE")
    order = db.get(Order, task.order_id)
    destination = f"HANDOFF:{normalized_handoff}"
    ensure_virtual_location(db, destination)
    balances = db.scalars(select(InventoryBalance).where(
        InventoryBalance.location_id == task.stage_location_id,
        InventoryBalance.qty_on_hand > 0,
    )).all()
    for bal in balances:
        move_inventory(
            db,
            event_id=f"handoff:{task.id}:{bal.product_id}:{task.server_version}",
            product_id=bal.product_id,
            qty=bal.qty_on_hand,
            source_location_id=task.stage_location_id,
            destination_location_id=destination,
            reason="HANDOFF",
            order_id=order.id,
            task_id=task.id,
            user_id=user_id,
            device_id=device_id,
        )
    task.handoff_ref = handoff_ref
    task.status = TaskStatus.HANDED_OFF.value
    order.status = OrderStatus.HANDED_OFF.value
    task.server_version += 1
    audit(db, "ORDER_HANDED_OFF", "PICK_TASK", task.id, user_id=user_id, device_id=device_id, payload={"handoff_ref": handoff_ref})
    db.flush()
    return task_snapshot(db, task)


def complete_delivery(db: Session, task: PickTask, user_id: str | None = None, device_id: str | None = None) -> dict:
    if task.status == TaskStatus.COMPLETED.value:
        return task_snapshot(db, task)
    if task.status != TaskStatus.HANDED_OFF.value:
        raise FulfillmentError(f"Task cannot complete from {task.status}", "INVALID_STATE")
    order = db.get(Order, task.order_id)
    source = f"HANDOFF:{task.handoff_ref.strip().upper()}"
    balances = db.scalars(select(InventoryBalance).where(
        InventoryBalance.location_id == source,
        InventoryBalance.qty_on_hand > 0,
    )).all()
    for bal in balances:
        move_inventory(
            db,
            event_id=f"delivered:{task.id}:{bal.product_id}",
            product_id=bal.product_id,
            qty=bal.qty_on_hand,
            source_location_id=source,
            destination_location_id=None,
            reason="DELIVERED",
            order_id=order.id,
            task_id=task.id,
            user_id=user_id,
            device_id=device_id,
        )
    task.status = TaskStatus.COMPLETED.value
    order.status = OrderStatus.COMPLETED.value
    task.finished_at = datetime.now(timezone.utc)
    task.server_version += 1
    release_pick_lease(db, task, reason="ORDER_COMPLETED")
    audit(db, "ORDER_COMPLETED", "PICK_TASK", task.id, user_id=user_id, device_id=device_id)
    db.flush()
    return task_snapshot(db, task)
