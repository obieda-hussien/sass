from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from .enums import OrderState, TaskState
from .location_parser import is_compatible, parse_location
from .models import (
    Associate,
    Barcode,
    InventoryBalance,
    InventoryMovement,
    Location,
    Order,
    OrderLine,
    OutboxEvent,
    Product,
    ScanEvent,
    Task,
    TaskLine,
)
from .schemas import OrderCreate, ScanPickRequest, ShortPickRequest
from .serializers import task_dict


def now() -> datetime:
    return datetime.now(timezone.utc)


def emit(
    db: Session,
    *,
    topic: str,
    aggregate_type: str,
    aggregate_id: str,
    payload: dict,
) -> None:
    db.add(
        OutboxEvent(
            topic=topic,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            payload_json=json.dumps(payload, default=str, separators=(",", ":")),
        )
    )


def load_task(db: Session, task_id: str, *, lock: bool = False) -> Task:
    stmt = (
        select(Task)
        .where(Task.id == task_id)
        .options(
            joinedload(Task.order),
            selectinload(Task.lines).joinedload(TaskLine.product),
            selectinload(Task.lines).joinedload(TaskLine.location),
        )
    )
    if lock:
        stmt = stmt.with_for_update()
    task = db.scalar(stmt)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


def find_product(db: Session, sku: str, *, lock: bool = False) -> Product:
    stmt = select(Product).where(Product.sku == sku)
    if lock:
        stmt = stmt.with_for_update()
    product = db.scalar(stmt)
    if not product:
        raise HTTPException(status_code=404, detail=f"Unknown SKU: {sku}")
    return product


def find_location(db: Session, code: str, *, lock: bool = False) -> Location:
    normalized = code.strip().upper().replace(" ", "")
    stmt = select(Location).where(Location.code == normalized)
    if lock:
        stmt = stmt.with_for_update()
    location = db.scalar(stmt)
    if not location:
        raise HTTPException(status_code=404, detail=f"Unknown location: {normalized}")
    return location


def ensure_location(
    db: Session,
    code: str,
    *,
    handling_class_override: str | None = None,
    pickable: bool = True,
    stowable: bool = True,
) -> Location:
    normalized = code.strip().upper().replace(" ", "")
    existing = db.scalar(select(Location).where(Location.code == normalized))
    if existing:
        return existing

    parsed = parse_location(normalized)
    location = Location(
        code=parsed.code,
        kind=parsed.kind.value,
        floor=parsed.floor,
        fixture=parsed.fixture,
        aisle=parsed.aisle,
        level=parsed.level,
        slot=parsed.slot,
        temperature_class=parsed.temperature.value,
        handling_class=handling_class_override or parsed.handling.value,
        pickable=pickable,
        stowable=stowable,
    )
    db.add(location)
    db.flush()
    return location


def get_or_create_balance(
    db: Session,
    *,
    product_id: str,
    location_id: str,
    lock: bool = False,
) -> InventoryBalance:
    stmt = select(InventoryBalance).where(
        InventoryBalance.product_id == product_id,
        InventoryBalance.location_id == location_id,
    )
    if lock:
        stmt = stmt.with_for_update()
    balance = db.scalar(stmt)
    if balance:
        return balance

    balance = InventoryBalance(product_id=product_id, location_id=location_id)
    db.add(balance)
    db.flush()
    return balance


def create_product(
    db: Session,
    *,
    sku: str,
    title: str,
    barcode: str,
    temperature_class: str,
    handling_class: str,
) -> Product:
    product = Product(
        sku=sku.strip(),
        title=title.strip(),
        temperature_class=temperature_class.upper(),
        handling_class=handling_class.upper(),
    )
    db.add(product)
    db.flush()
    db.add(Barcode(code=barcode.strip(), product_id=product.id))
    emit(
        db,
        topic="catalog.product.created",
        aggregate_type="product",
        aggregate_id=product.id,
        payload={"sku": product.sku},
    )
    return product


def adjust_inventory(
    db: Session,
    *,
    event_id: str,
    product_sku: str,
    location_code: str,
    delta: int,
    reason: str,
    actor_id: str | None,
    device_id: str | None,
) -> InventoryBalance:
    duplicate = db.scalar(
        select(InventoryMovement).where(InventoryMovement.event_id == event_id)
    )
    if duplicate:
        product = find_product(db, product_sku)
        location = find_location(db, location_code)
        return get_or_create_balance(
            db, product_id=product.id, location_id=location.id, lock=True
        )

    product = find_product(db, product_sku)
    location = find_location(db, location_code)
    balance = get_or_create_balance(
        db, product_id=product.id, location_id=location.id, lock=True
    )
    if balance.on_hand + delta < 0:
        raise HTTPException(status_code=409, detail="Insufficient on-hand inventory")

    balance.on_hand += delta
    balance.version += 1
    db.add(
        InventoryMovement(
            event_id=event_id,
            product_id=product.id,
            quantity=abs(delta),
            source_location_id=location.id if delta < 0 else None,
            destination_location_id=location.id if delta > 0 else None,
            reason=reason,
            actor_id=actor_id,
            device_id=device_id,
        )
    )
    emit(
        db,
        topic="inventory.adjusted",
        aggregate_type="inventory",
        aggregate_id=balance.id,
        payload={
            "eventId": event_id,
            "sku": product.sku,
            "location": location.code,
            "delta": delta,
            "version": balance.version,
        },
    )
    return balance


def move_inventory(
    db: Session,
    *,
    event_id: str,
    product_sku: str,
    source_code: str,
    destination_code: str,
    quantity: int,
    reason: str,
    actor_id: str | None,
    device_id: str | None,
) -> dict:
    existing = db.scalar(
        select(InventoryMovement).where(InventoryMovement.event_id == event_id)
    )
    if existing:
        return {"eventId": event_id, "status": "DUPLICATE"}

    product = find_product(db, product_sku)
    source = find_location(db, source_code)
    destination = find_location(db, destination_code)

    parsed_destination = parse_location(destination.code)
    compatible = is_compatible(
        product_temperature=product.temperature_class,  # type: ignore[arg-type]
        product_handling=product.handling_class,  # type: ignore[arg-type]
        location=parsed_destination,
    )
    # HRV can be represented by site metadata rather than grammar.
    if product.handling_class == "HRV":
        compatible = destination.handling_class in {"HRV", "SPECIAL"}
    if not compatible:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{product.sku} ({product.temperature_class}/{product.handling_class}) "
                f"is not compatible with {destination.code}"
            ),
        )

    source_balance = get_or_create_balance(
        db, product_id=product.id, location_id=source.id, lock=True
    )
    if source_balance.on_hand - source_balance.reserved < quantity:
        raise HTTPException(status_code=409, detail="Insufficient available inventory")

    destination_balance = get_or_create_balance(
        db, product_id=product.id, location_id=destination.id, lock=True
    )

    source_balance.on_hand -= quantity
    source_balance.version += 1
    destination_balance.on_hand += quantity
    destination_balance.version += 1

    movement = InventoryMovement(
        event_id=event_id,
        product_id=product.id,
        quantity=quantity,
        source_location_id=source.id,
        destination_location_id=destination.id,
        reason=reason,
        actor_id=actor_id,
        device_id=device_id,
    )
    db.add(movement)
    emit(
        db,
        topic="inventory.moved",
        aggregate_type="inventory",
        aggregate_id=product.id,
        payload={
            "eventId": event_id,
            "sku": product.sku,
            "source": source.code,
            "destination": destination.code,
            "quantity": quantity,
            "reason": reason,
        },
    )
    return {"eventId": event_id, "status": "COMMITTED"}


def create_order_and_task(db: Session, request: OrderCreate) -> Task:
    if db.scalar(select(Order).where(Order.external_ref == request.external_ref)):
        raise HTTPException(status_code=409, detail="Order external_ref already exists")

    order = Order(external_ref=request.external_ref, priority=request.priority, state="CREATED")
    db.add(order)
    db.flush()

    task = Task(order_id=order.id, state=TaskState.READY.value)
    db.add(task)
    db.flush()

    sequence = 1
    for requested in request.lines:
        product = find_product(db, requested.sku)
        order_line = OrderLine(
            order_id=order.id,
            product_id=product.id,
            requested_qty=requested.quantity,
        )
        db.add(order_line)
        db.flush()

        remaining = requested.quantity
        balances = db.scalars(
            select(InventoryBalance)
            .join(Location, InventoryBalance.location_id == Location.id)
            .where(
                InventoryBalance.product_id == product.id,
                Location.pickable.is_(True),
                InventoryBalance.on_hand > InventoryBalance.reserved,
            )
            .order_by(Location.code)
            .with_for_update()
        ).all()

        for balance in balances:
            if remaining <= 0:
                break
            allocate = min(remaining, balance.available)
            if allocate <= 0:
                continue
            balance.reserved += allocate
            balance.version += 1
            order_line.allocated_qty += allocate
            db.add(
                TaskLine(
                    task_id=task.id,
                    order_line_id=order_line.id,
                    product_id=product.id,
                    location_id=balance.location_id,
                    sequence=sequence,
                    required_qty=allocate,
                )
            )
            sequence += 1
            remaining -= allocate

        if remaining:
            raise HTTPException(
                status_code=409,
                detail=f"Insufficient inventory for {product.sku}: short {remaining}",
            )

    order.state = OrderState.ALLOCATED.value
    emit(
        db,
        topic="fulfillment.task.ready",
        aggregate_type="task",
        aggregate_id=task.id,
        payload={"orderId": order.id, "taskId": task.id},
    )
    db.flush()
    return load_task(db, task.id)


def offer_next_task(db: Session, associate_id: str) -> Task | None:
    task = db.scalar(
        select(Task)
        .join(Order, Task.order_id == Order.id)
        .where(Task.state == TaskState.READY.value)
        .order_by(Order.priority.desc(), Order.created_at.asc())
        .with_for_update(skip_locked=True)
    )
    if not task:
        return None

    task.state = TaskState.OFFERED.value
    task.associate_id = associate_id
    task.offered_at = now()
    task.version += 1

    associate = db.get(Associate, associate_id)
    if not associate:
        associate = Associate(id=associate_id, display_name=associate_id)
        db.add(associate)
    associate.state = "OFFERED"
    associate.active_task_id = task.id
    associate.updated_at = now()
    db.flush()
    return load_task(db, task.id)


def accept_task(db: Session, task_id: str, *, associate_id: str, device_id: str) -> Task:
    task = load_task(db, task_id, lock=True)
    if task.state != TaskState.OFFERED.value or task.associate_id != associate_id:
        raise HTTPException(status_code=409, detail="Task is not offered to this associate")

    task.state = TaskState.PICKING.value
    task.accepted_at = now()
    task.version += 1
    task.order.state = OrderState.PICKING.value

    associate = db.get(Associate, associate_id)
    if associate:
        associate.state = "PICKING"
        associate.active_task_id = task.id
        associate.updated_at = now()

    emit(
        db,
        topic="fulfillment.task.accepted",
        aggregate_type="task",
        aggregate_id=task.id,
        payload={"associateId": associate_id, "deviceId": device_id},
    )
    db.flush()
    return load_task(db, task.id)


def _validate_client_version(task: Task, client_version: int) -> None:
    if task.version != client_version:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "STALE_TASK_VERSION",
                "clientVersion": client_version,
                "serverVersion": task.version,
                "task": task_dict(task),
            },
        )


def commit_pick_scan(db: Session, task_id: str, request: ScanPickRequest) -> dict:
    duplicate = db.scalar(select(ScanEvent).where(ScanEvent.event_id == request.event_id))
    if duplicate:
        task = load_task(db, task_id)
        return {
            "status": "DUPLICATE",
            "eventId": request.event_id,
            "task": task_dict(task),
        }

    task = load_task(db, task_id, lock=True)
    if task.state != TaskState.PICKING.value:
        raise HTTPException(status_code=409, detail=f"Task is {task.state}, not PICKING")
    if task.associate_id != request.associate_id:
        raise HTTPException(status_code=403, detail="Task belongs to another associate")

    _validate_client_version(task, request.client_task_version)

    line = db.scalar(
        select(TaskLine)
        .where(TaskLine.id == request.task_line_id, TaskLine.task_id == task.id)
        .with_for_update()
    )
    if not line:
        raise HTTPException(status_code=404, detail="Task line not found")

    location = db.get(Location, line.location_id)
    if not location or location.code != request.location_code.strip().upper().replace(" ", ""):
        raise HTTPException(
            status_code=409,
            detail={"code": "WRONG_BIN", "expected": location.code if location else None},
        )

    barcode = db.get(Barcode, request.barcode.strip())
    if not barcode or barcode.product_id != line.product_id:
        raise HTTPException(status_code=409, detail={"code": "WRONG_ITEM"})

    remaining = line.required_qty - line.picked_qty - line.short_qty
    if request.quantity > remaining:
        raise HTTPException(status_code=409, detail="Quantity exceeds remaining line quantity")

    balance = get_or_create_balance(
        db, product_id=line.product_id, location_id=line.location_id, lock=True
    )
    if balance.on_hand < request.quantity or balance.reserved < request.quantity:
        raise HTTPException(status_code=409, detail="Inventory reservation is no longer valid")

    order_line = db.get(OrderLine, line.order_line_id)
    balance.on_hand -= request.quantity
    balance.reserved -= request.quantity
    balance.version += 1
    line.picked_qty += request.quantity
    if order_line:
        order_line.picked_qty += request.quantity

    event = ScanEvent(
        event_id=request.event_id,
        task_id=task.id,
        task_line_id=line.id,
        associate_id=request.associate_id,
        device_id=request.device_id,
        client_sequence=request.client_sequence,
        client_task_version=request.client_task_version,
        quantity=request.quantity,
        status="COMMITTED",
    )
    db.add(event)
    db.add(
        InventoryMovement(
            event_id=request.event_id,
            product_id=line.product_id,
            quantity=request.quantity,
            source_location_id=line.location_id,
            destination_location_id=None,
            reason="ORDER_PICK",
            actor_id=request.associate_id,
            device_id=request.device_id,
            task_id=task.id,
        )
    )

    task.version += 1

    if all(
        task_line.picked_qty + task_line.short_qty >= task_line.required_qty
        for task_line in task.lines
    ):
        task.state = TaskState.PACKING_RACKING.value
        task.order.state = OrderState.PICKED.value
        associate = db.get(Associate, request.associate_id)
        if associate:
            associate.state = "PACKING_RACKING"
            associate.updated_at = now()

    emit(
        db,
        topic="fulfillment.pick.committed",
        aggregate_type="task",
        aggregate_id=task.id,
        payload={
            "eventId": request.event_id,
            "lineId": line.id,
            "quantity": request.quantity,
            "serverTaskVersion": task.version,
        },
    )

    try:
        db.flush()
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Duplicate client sequence") from exc

    return {
        "status": "COMMITTED",
        "eventId": request.event_id,
        "task": task_dict(load_task(db, task.id)),
    }


def commit_short_pick(db: Session, task_id: str, request: ShortPickRequest) -> dict:
    duplicate = db.scalar(select(ScanEvent).where(ScanEvent.event_id == request.event_id))
    if duplicate:
        return {
            "status": "DUPLICATE",
            "eventId": request.event_id,
            "task": task_dict(load_task(db, task_id)),
        }

    task = load_task(db, task_id, lock=True)
    if task.state != TaskState.PICKING.value:
        raise HTTPException(status_code=409, detail="Task is not PICKING")
    if task.associate_id != request.associate_id:
        raise HTTPException(status_code=403, detail="Task belongs to another associate")
    _validate_client_version(task, request.client_task_version)

    line = db.scalar(
        select(TaskLine)
        .where(TaskLine.id == request.task_line_id, TaskLine.task_id == task.id)
        .with_for_update()
    )
    if not line:
        raise HTTPException(status_code=404, detail="Task line not found")

    remaining = line.required_qty - line.picked_qty - line.short_qty
    if request.quantity > remaining:
        raise HTTPException(status_code=409, detail="Short quantity exceeds remaining")

    balance = get_or_create_balance(
        db, product_id=line.product_id, location_id=line.location_id, lock=True
    )
    release = min(request.quantity, balance.reserved)
    balance.reserved -= release
    balance.version += 1
    line.short_qty += request.quantity
    task.version += 1

    db.add(
        ScanEvent(
            event_id=request.event_id,
            task_id=task.id,
            task_line_id=line.id,
            associate_id=request.associate_id,
            device_id=request.device_id,
            client_sequence=request.client_sequence,
            client_task_version=request.client_task_version,
            quantity=request.quantity,
            status="COMMITTED",
        )
    )

    if all(
        task_line.picked_qty + task_line.short_qty >= task_line.required_qty
        for task_line in task.lines
    ):
        task.state = TaskState.PACKING_RACKING.value
        task.order.state = OrderState.PICKED.value

    emit(
        db,
        topic="fulfillment.pick.short",
        aggregate_type="task",
        aggregate_id=task.id,
        payload={
            "eventId": request.event_id,
            "lineId": line.id,
            "quantity": request.quantity,
            "reason": request.reason,
        },
    )
    db.flush()
    return {"status": "COMMITTED", "task": task_dict(load_task(db, task.id))}


def cancel_task(db: Session, task_id: str, *, reason: str, actor_id: str | None) -> Task:
    task = load_task(db, task_id, lock=True)
    if task.state in {
        TaskState.CANCELLED.value,
        TaskState.COMPLETED.value,
        TaskState.HANDED_OFF.value,
    }:
        return task

    picked_total = sum(line.picked_qty for line in task.lines)

    for line in task.lines:
        unpicked_reserved = max(0, line.required_qty - line.picked_qty - line.short_qty)
        if unpicked_reserved:
            balance = get_or_create_balance(
                db, product_id=line.product_id, location_id=line.location_id, lock=True
            )
            release = min(balance.reserved, unpicked_reserved)
            balance.reserved -= release
            balance.version += 1

    task.cancel_reason = reason
    task.version += 1
    task.order.cancelled_at = now()

    if picked_total > 0:
        task.state = TaskState.RECOVERY_REQUIRED.value
        task.recovery_reason = "ORDER_CANCELLED_AFTER_PICK_COMMIT"
        task.order.state = OrderState.RECOVERY_REQUIRED.value
    else:
        task.state = TaskState.CANCELLED.value
        task.order.state = OrderState.CANCELLED.value

    associate = db.get(Associate, task.associate_id) if task.associate_id else None
    if associate:
        associate.state = "WAITING"
        associate.active_task_id = None
        associate.updated_at = now()

    emit(
        db,
        topic="fulfillment.task.cancelled",
        aggregate_type="task",
        aggregate_id=task.id,
        payload={
            "reason": reason,
            "actorId": actor_id,
            "state": task.state,
            "pickedTotal": picked_total,
        },
    )
    db.flush()
    return load_task(db, task.id)


def stage_task(
    db: Session,
    task_id: str,
    *,
    location_code: str,
    associate_id: str,
    device_id: str,
) -> Task:
    task = load_task(db, task_id, lock=True)
    if task.state != TaskState.PACKING_RACKING.value:
        raise HTTPException(status_code=409, detail="Task is not ready for staging")

    task.state = TaskState.STAGED.value
    task.order.state = OrderState.STAGED.value
    task.version += 1
    emit(
        db,
        topic="fulfillment.task.staged",
        aggregate_type="task",
        aggregate_id=task.id,
        payload={
            "stageLocation": location_code,
            "associateId": associate_id,
            "deviceId": device_id,
        },
    )
    db.flush()
    return load_task(db, task.id)


def handoff_task(
    db: Session,
    task_id: str,
    *,
    associate_id: str,
    device_id: str,
    rider_ref: str | None,
) -> Task:
    task = load_task(db, task_id, lock=True)
    if task.state != TaskState.STAGED.value:
        raise HTTPException(status_code=409, detail="Task is not staged")

    task.state = TaskState.HANDED_OFF.value
    task.order.state = OrderState.HANDED_OFF.value
    task.completed_at = now()
    task.version += 1

    associate = db.get(Associate, task.associate_id) if task.associate_id else None
    if associate:
        associate.state = "WAITING"
        associate.active_task_id = None
        associate.updated_at = now()

    emit(
        db,
        topic="fulfillment.task.handed_off",
        aggregate_type="task",
        aggregate_id=task.id,
        payload={
            "associateId": associate_id,
            "deviceId": device_id,
            "riderRef": rider_ref,
        },
    )
    db.flush()
    return load_task(db, task.id)


def control_tower_summary(db: Session) -> dict:
    associate_counts = dict(
        db.execute(
            select(Associate.state, func.count(Associate.id)).group_by(Associate.state)
        ).all()
    )
    task_counts = dict(
        db.execute(select(Task.state, func.count(Task.id)).group_by(Task.state)).all()
    )

    recovery = db.scalars(
        select(Task)
        .where(Task.state == TaskState.RECOVERY_REQUIRED.value)
        .order_by(Task.accepted_at.asc())
        .limit(20)
    ).all()

    return {
        "associates": associate_counts,
        "tasks": task_counts,
        "recoveryRequired": [
            {
                "taskId": task.id,
                "orderId": task.order_id,
                "associateId": task.associate_id,
                "reason": task.recovery_reason,
                "version": task.version,
            }
            for task in recovery
        ],
    }
