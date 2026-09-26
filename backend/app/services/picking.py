from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    Barcode,
    InventoryBalance,
    InventoryMovement,
    Location,
    Order,
    OrderLine,
    OrderStatus,
    PickTask,
    PickTaskItem,
    Product,
    ScanEvent,
    TaskStatus,
)
from .compatibility import storage_compatible
from .inventory import InventoryError, move_inventory


class PickError(Exception):
    def __init__(self, message: str, code: str = "PICK_ERROR"):
        super().__init__(message)
        self.code = code


@dataclass
class PickAck:
    duplicate: bool
    snapshot: dict


def ensure_virtual_location(db: Session, location_id: str, handling: str = "STANDARD") -> None:
    if db.get(Location, location_id) is None:
        db.add(Location(
            id=location_id,
            classification="LOGICAL",
            logical=True,
            pickable=False,
            stowable=True,
            sellable=False,
            handling_class=handling,
            temperature_class="AMBIENT",
        ))
        db.flush()


def _catalog_item(db: Session, product_id: str) -> dict:
    product = db.get(Product, product_id)
    barcodes = list(db.scalars(select(Barcode.code).where(Barcode.product_id == product_id)).all())
    return {
        "asin": product.asin if product else None,
        "title": product.title if product else "Unknown product",
        "temperature_class": product.temperature_class if product else None,
        "handling_class": product.handling_class if product else None,
        "barcodes": barcodes,
    }


def task_snapshot(db: Session, task: PickTask) -> dict:
    items = db.scalars(
        select(PickTaskItem)
        .where(PickTaskItem.task_id == task.id)
        .order_by(PickTaskItem.sequence)
    ).all()
    order = db.get(Order, task.order_id)
    lines = db.scalars(select(OrderLine).where(OrderLine.order_id == task.order_id)).all()
    shorted_units = sum(line.shorted_qty for line in lines)
    picked_units = sum(item.picked_qty for item in items)

    item_payloads = []
    for item in items:
        catalog = _catalog_item(db, item.product_id)
        item_payloads.append({
            "id": item.id,
            "product_id": item.product_id,
            "source_location_id": item.source_location_id,
            "planned_qty": item.planned_qty,
            "picked_qty": item.picked_qty,
            "remaining_qty": max(0, item.planned_qty - item.picked_qty),
            "sequence": item.sequence,
            **catalog,
        })

    return {
        "task_id": task.id,
        "order_id": task.order_id,
        "task_status": task.status,
        "order_status": order.status if order else None,
        "server_version": task.server_version,
        "client_high_water_seq": task.client_high_water_seq,
        "expected_units": task.expected_units,
        "picked_units": picked_units,
        "shorted_units": shorted_units,
        "processed_units": picked_units + shorted_units,
        "remaining_units": sum(max(0, i.planned_qty - i.picked_qty) for i in items),
        "recovery_required": bool(order.recovery_required) if order else False,
        "items": item_payloads,
    }


def accept_task(db: Session, task: PickTask, user_id: str, device_id: str) -> dict:
    if task.status in {TaskStatus.ACCEPTED.value, TaskStatus.PICKING.value}:
        if task.assigned_user_id == user_id and task.assigned_device_id == device_id:
            return task_snapshot(db, task)
        raise PickError("Task is already owned by another associate/device", "OWNERSHIP_MISMATCH")
    if task.status not in {TaskStatus.OFFERED.value, TaskStatus.READY.value}:
        raise PickError(f"Task cannot be accepted from {task.status}", "INVALID_STATE")
    if task.assigned_user_id and task.assigned_user_id != user_id:
        raise PickError("Task is assigned to another associate", "ASSIGNMENT_MISMATCH")
    if task.assigned_device_id and task.assigned_device_id != device_id:
        raise PickError("Task is assigned to another device", "DEVICE_MISMATCH")
    now = datetime.now(timezone.utc)
    task.assigned_user_id = user_id
    task.assigned_device_id = device_id
    task.status = TaskStatus.ACCEPTED.value
    task.accepted_at = now
    task.server_version += 1
    order = db.get(Order, task.order_id)
    if order:
        order.status = OrderStatus.PICKING.value
    db.flush()
    return task_snapshot(db, task)


def _validate_barcode(db: Session, barcode: str | None, product_id: str) -> None:
    if barcode is None:
        return
    normalized = barcode.strip()
    if not normalized:
        raise PickError("Empty product barcode", "BARCODE_MISMATCH")
    mapped = db.scalar(select(Barcode).where(Barcode.code == normalized))
    if mapped is None or mapped.product_id != product_id:
        raise PickError("Scanned barcode does not belong to the expected product", "BARCODE_MISMATCH")


def commit_pick(
    db: Session,
    *,
    task: PickTask,
    event_id: str,
    client_seq: int,
    task_item_id: str,
    location_id: str,
    product_id: str,
    qty: int,
    user_id: str,
    device_id: str,
    barcode: str | None = None,
) -> PickAck:
    existing = db.get(ScanEvent, event_id)
    if existing:
        return PickAck(True, task_snapshot(db, task))

    if task.status in {TaskStatus.CANCEL_PENDING.value, TaskStatus.CANCELLED.value, TaskStatus.RECOVERY_REQUIRED.value}:
        raise PickError("Order changed state and requires reconciliation", "TASK_CANCELLED_OR_RECOVERY")
    if task.status not in {TaskStatus.ACCEPTED.value, TaskStatus.PICKING.value}:
        raise PickError(f"Task is not pickable in state {task.status}", "INVALID_STATE")
    if task.assigned_user_id != user_id or task.assigned_device_id != device_id:
        raise PickError("Associate/device does not own this task", "OWNERSHIP_MISMATCH")
    if client_seq != task.client_high_water_seq + 1:
        raise PickError(
            f"Out-of-order client sequence; expected {task.client_high_water_seq + 1}, got {client_seq}",
            "SEQUENCE_CONFLICT",
        )

    item = db.get(PickTaskItem, task_item_id)
    if not item or item.task_id != task.id:
        raise PickError("Task item does not belong to task", "ITEM_MISMATCH")
    if item.product_id != product_id:
        raise PickError("Wrong product", "PRODUCT_MISMATCH")
    if item.source_location_id != location_id:
        raise PickError("Wrong bin/location", "LOCATION_MISMATCH")

    _validate_barcode(db, barcode, product_id)

    remaining = item.planned_qty - item.picked_qty
    if qty > remaining:
        raise PickError(f"Quantity exceeds remaining planned quantity {remaining}", "QTY_EXCEEDS_PLAN")

    order = db.get(Order, task.order_id)
    if not order:
        raise PickError("Order missing", "ORDER_MISSING")
    tote_location = f"PICKTOTE:{order.id}"
    ensure_virtual_location(db, tote_location)

    try:
        move_inventory(
            db,
            event_id=f"move:{event_id}",
            product_id=product_id,
            qty=qty,
            source_location_id=location_id,
            destination_location_id=tote_location,
            reason="PICK",
            order_id=order.id,
            task_id=task.id,
            user_id=user_id,
            device_id=device_id,
            consume_reserved=True,
        )
    except InventoryError as e:
        raise PickError(str(e), "INVENTORY_CONFLICT") from e

    item.picked_qty += qty
    line = db.get(OrderLine, item.order_line_id)
    if line:
        line.picked_qty += qty
    now = datetime.now(timezone.utc)
    task.status = TaskStatus.PICKING.value
    task.started_at = task.started_at or now
    task.client_high_water_seq = client_seq
    task.server_version += 1

    payload = {
        "task_item_id": task_item_id,
        "location_id": location_id,
        "product_id": product_id,
        "qty": qty,
        "barcode": barcode,
    }
    db.add(ScanEvent(
        id=event_id,
        task_id=task.id,
        client_seq=client_seq,
        device_id=device_id,
        user_id=user_id,
        event_type="PICK",
        status="ACKED",
        payload_json=json.dumps(payload, separators=(",", ":")),
        server_version_after=task.server_version,
    ))

    remaining_total = db.scalar(
        select(func.sum(PickTaskItem.planned_qty - PickTaskItem.picked_qty))
        .where(PickTaskItem.task_id == task.id)
    ) or 0
    if remaining_total <= 0:
        task.status = TaskStatus.PICKED.value
        task.finished_at = now
        order.status = OrderStatus.PICKED.value
        task.server_version += 1

    db.flush()
    return PickAck(False, task_snapshot(db, task))


def short_pick(
    db: Session,
    *,
    task: PickTask,
    event_id: str,
    client_seq: int,
    task_item_id: str,
    qty: int,
    reason: str,
    user_id: str,
    device_id: str,
) -> PickAck:
    """Confirm a real shelf shortage without making phantom stock available again."""
    existing = db.get(ScanEvent, event_id)
    if existing:
        return PickAck(True, task_snapshot(db, task))

    if task.status in {TaskStatus.CANCEL_PENDING.value, TaskStatus.CANCELLED.value, TaskStatus.RECOVERY_REQUIRED.value}:
        raise PickError("Order changed state and requires reconciliation", "TASK_CANCELLED_OR_RECOVERY")
    if task.status not in {TaskStatus.ACCEPTED.value, TaskStatus.PICKING.value}:
        raise PickError(f"Task is not shortable in state {task.status}", "INVALID_STATE")
    if task.assigned_user_id != user_id or task.assigned_device_id != device_id:
        raise PickError("Associate/device does not own this task", "OWNERSHIP_MISMATCH")
    if client_seq != task.client_high_water_seq + 1:
        raise PickError(
            f"Out-of-order client sequence; expected {task.client_high_water_seq + 1}, got {client_seq}",
            "SEQUENCE_CONFLICT",
        )

    item = db.get(PickTaskItem, task_item_id)
    if not item or item.task_id != task.id:
        raise PickError("Task item does not belong to task", "ITEM_MISMATCH")
    remaining = item.planned_qty - item.picked_qty
    if qty <= 0 or qty > remaining:
        raise PickError(f"Invalid shortage quantity; remaining={remaining}", "QTY_EXCEEDS_PLAN")

    order = db.get(Order, task.order_id)
    if not order:
        raise PickError("Order missing", "ORDER_MISSING")

    # The picker has physically verified the expected unit is absent from this location.
    # Remove that unit from on-hand while consuming the reservation atomically so the
    # allocator cannot immediately promise the same phantom stock to another order.
    try:
        move_inventory(
            db,
            event_id=f"short-move:{event_id}",
            product_id=item.product_id,
            qty=qty,
            source_location_id=item.source_location_id,
            destination_location_id=None,
            reason=f"SHORT:{reason[:48]}",
            order_id=order.id,
            task_id=task.id,
            user_id=user_id,
            device_id=device_id,
            consume_reserved=True,
        )
    except InventoryError as e:
        raise PickError(str(e), "INVENTORY_CONFLICT") from e

    item.planned_qty -= qty
    line = db.get(OrderLine, item.order_line_id)
    if line:
        line.shorted_qty += qty

    now = datetime.now(timezone.utc)
    task.status = TaskStatus.PICKING.value
    task.started_at = task.started_at or now
    task.client_high_water_seq = client_seq
    task.server_version += 1

    db.add(ScanEvent(
        id=event_id,
        task_id=task.id,
        client_seq=client_seq,
        device_id=device_id,
        user_id=user_id,
        event_type="SHORT",
        status="ACKED",
        payload_json=json.dumps(
            {
                "task_item_id": item.id,
                "location_id": item.source_location_id,
                "product_id": item.product_id,
                "qty": qty,
                "reason": reason,
            },
            separators=(",", ":"),
        ),
        server_version_after=task.server_version,
    ))

    remaining_total = db.scalar(
        select(func.sum(PickTaskItem.planned_qty - PickTaskItem.picked_qty))
        .where(PickTaskItem.task_id == task.id)
    ) or 0
    if remaining_total <= 0:
        task.status = TaskStatus.PICKED.value
        task.finished_at = now
        order.status = OrderStatus.PICKED.value
        task.server_version += 1

    db.flush()
    return PickAck(False, task_snapshot(db, task))


def _recovery_source(task: PickTask, order: Order) -> tuple[str | None, str]:
    if task.handoff_ref:
        return f"HANDOFF:{task.handoff_ref.strip().upper()}", "HANDOFF_RETURN"
    if task.stage_location_id:
        return task.stage_location_id, "STAGED_STOW"
    return f"PICKTOTE:{order.id}", "PICK_TOTE_STOW"


def recovery_snapshot(db: Session, task: PickTask) -> dict:
    order = db.get(Order, task.order_id)
    if not order:
        raise PickError("Order missing", "ORDER_MISSING")
    source, recovery_type = _recovery_source(task, order)
    balances = []
    if source:
        balances = db.scalars(
            select(InventoryBalance).where(
                InventoryBalance.location_id == source,
                InventoryBalance.qty_on_hand > 0,
            )
        ).all()

    items = []
    for bal in balances:
        product = db.get(Product, bal.product_id)
        candidate_locations = db.scalars(
            select(Location).where(
                Location.logical == False,  # noqa: E712
                Location.stowable == True,  # noqa: E712
                Location.sellable == True,  # noqa: E712
            )
        ).all()
        compatible = [
            loc.id for loc in candidate_locations
            if product is not None and storage_compatible(product, loc)[0]
        ]
        items.append({
            "product_id": bal.product_id,
            "asin": product.asin if product else None,
            "title": product.title if product else "Unknown product",
            "qty": bal.qty_on_hand,
            "source_location_id": source,
            "compatible_destinations": compatible[:20],
        })

    return {
        "task_id": task.id,
        "order_id": order.id,
        "order_status": order.status,
        "recovery_required": order.recovery_required,
        "recovery_type": recovery_type,
        "source_location_id": source,
        "items": items,
    }


def recover_stow(
    db: Session,
    *,
    task: PickTask,
    event_id: str,
    product_id: str,
    qty: int,
    destination_location_id: str,
    user_id: str,
    device_id: str,
) -> dict:
    existing = db.scalar(
        select(InventoryMovement).where(InventoryMovement.event_id == f"recovery:{event_id}")
    )
    if existing:
        return {
            "duplicate": True,
            "task_id": task.id,
            "order_id": task.order_id,
            "destination_location_id": existing.destination_location_id,
        }

    order = db.get(Order, task.order_id)
    if not order or not order.recovery_required or task.status != TaskStatus.RECOVERY_REQUIRED.value:
        raise PickError("Task does not require recovery", "RECOVERY_NOT_REQUIRED")

    source, recovery_type = _recovery_source(task, order)
    if recovery_type == "HANDOFF_RETURN":
        raise PickError(
            "Inventory has crossed handoff and requires a controlled return/check-in before stow",
            "HANDOFF_RETURN_REQUIRED",
        )

    product = db.get(Product, product_id)
    destination = db.get(Location, destination_location_id)
    if not product or not destination:
        raise PickError("Unknown product or destination", "NOT_FOUND")
    compatible, code = storage_compatible(product, destination)
    if not compatible:
        raise PickError(f"Incompatible recovery destination: {code}", code or "INCOMPATIBLE")

    try:
        moved = move_inventory(
            db,
            event_id=f"recovery:{event_id}",
            product_id=product_id,
            qty=qty,
            source_location_id=source,
            destination_location_id=destination_location_id,
            reason="RECOVERY_STOW",
            order_id=order.id,
            task_id=task.id,
            user_id=user_id,
            device_id=device_id,
        )
    except InventoryError as e:
        raise PickError(str(e), "INVENTORY_CONFLICT") from e

    remaining = db.scalar(
        select(func.sum(InventoryBalance.qty_on_hand)).where(
            InventoryBalance.location_id == source,
            InventoryBalance.qty_on_hand > 0,
        )
    ) or 0
    if remaining <= 0:
        order.recovery_required = False
        order.status = OrderStatus.CANCELLED.value
        task.status = TaskStatus.CANCELLED.value
        task.server_version += 1

    db.flush()
    return {
        "duplicate": moved.duplicate,
        "task_id": task.id,
        "order_id": order.id,
        "source_location_id": source,
        "destination_location_id": destination_location_id,
        "remaining_recovery_units": int(remaining),
        "recovery_complete": remaining <= 0,
        "task_status": task.status,
        "order_status": order.status,
    }


def release_task_reservations(db: Session, task: PickTask) -> None:
    items = db.scalars(select(PickTaskItem).where(PickTaskItem.task_id == task.id)).all()
    for item in items:
        remaining = max(0, item.planned_qty - item.picked_qty)
        if remaining <= 0:
            continue
        bal = db.scalar(select(InventoryBalance).where(
            InventoryBalance.location_id == item.source_location_id,
            InventoryBalance.product_id == item.product_id,
        ))
        if bal:
            released = min(remaining, bal.qty_reserved)
            bal.qty_reserved -= released
            bal.version += 1


def cancel_order(db: Session, order: Order, reason: str) -> dict:
    task = db.scalar(select(PickTask).where(PickTask.order_id == order.id))
    order.cancellation_reason = reason
    if not task:
        order.status = OrderStatus.CANCELLED.value
        return {"order_id": order.id, "status": order.status, "recovery_required": False}

    picked_units = db.scalar(select(func.sum(PickTaskItem.picked_qty)).where(PickTaskItem.task_id == task.id)) or 0
    release_task_reservations(db, task)
    if task.status in {TaskStatus.HANDED_OFF.value, TaskStatus.COMPLETED.value} or order.status in {OrderStatus.HANDED_OFF.value, OrderStatus.COMPLETED.value}:
        order.status = OrderStatus.RETURN_REQUIRED.value
        order.recovery_required = True
        task.status = TaskStatus.RECOVERY_REQUIRED.value
    elif picked_units > 0:
        order.status = OrderStatus.CANCELLED_RECOVERY.value
        order.recovery_required = True
        task.status = TaskStatus.RECOVERY_REQUIRED.value
    else:
        order.status = OrderStatus.CANCELLED.value
        task.status = TaskStatus.CANCELLED.value

    task.server_version += 1
    db.flush()
    return task_snapshot(db, task)
