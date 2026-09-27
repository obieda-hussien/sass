from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Barcode, InventoryBalance, Location, Product, User
from ..models_ops import (
    ActivePickLease,
    InventoryAlert,
    ReplenishmentEvent,
    ReplenishmentTask,
    WorkerRuntimeState,
)
from .compatibility import storage_compatible
from .inventory import InventoryError, move_inventory
from .ops_platform import OpsError, get_worker_state, set_worker_state


TERMINAL_STATUSES = {"COMPLETED", "PARTIAL", "CANCELLED", "FAILED"}
EXECUTABLE_STATUSES = {"READY", "ASSIGNED", "CLAIMED", "STARTED", "SOURCE_CONFIRMED", "DESTINATION_CONFIRMED"}


class ReplenishmentError(RuntimeError):
    def __init__(self, message: str, code: str = "REPLENISHMENT_ERROR"):
        super().__init__(message)
        self.code = code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _event(
    db: Session,
    *,
    event_id: str,
    task: ReplenishmentTask,
    user_id: str,
    device_id: str | None,
    event_type: str,
    qty: int = 0,
    source_location_id: str | None = None,
    destination_location_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> tuple[ReplenishmentEvent, bool]:
    existing = db.scalar(select(ReplenishmentEvent).where(ReplenishmentEvent.event_id == event_id))
    if existing:
        return existing, True
    row = ReplenishmentEvent(
        event_id=event_id,
        replenishment_task_id=task.id,
        user_id=user_id,
        device_id=device_id,
        event_type=event_type,
        qty=qty,
        source_location_id=source_location_id,
        destination_location_id=destination_location_id,
        payload_json=json.dumps(payload or {}, separators=(",", ":")),
    )
    db.add(row)
    db.flush()
    return row, False


def _ensure_available_worker(db: Session, user_id: str) -> User:
    user = db.get(User, user_id)
    if user is None or not user.active:
        raise ReplenishmentError("Worker not found or inactive", "WORKER_UNAVAILABLE")
    if db.get(ActivePickLease, user_id):
        raise ReplenishmentError("Worker has an active pick order", "ACTIVE_PICK_EXISTS")
    state = get_worker_state(db, user_id, create=True)
    if state is None or state.state != "AVAILABLE":
        raise ReplenishmentError(
            f"Worker is not available ({state.state if state else 'OFFLINE'})",
            "WORKER_NOT_AVAILABLE",
        )
    return user


def task_payload(db: Session, task: ReplenishmentTask) -> dict[str, Any]:
    product = db.get(Product, task.product_id)
    source_balance = db.scalar(
        select(InventoryBalance).where(
            InventoryBalance.product_id == task.product_id,
            InventoryBalance.location_id == task.source_location_id,
        )
    )
    destination_balance = db.scalar(
        select(InventoryBalance).where(
            InventoryBalance.product_id == task.product_id,
            InventoryBalance.location_id == task.destination_location_id,
        )
    )
    return {
        "id": task.id,
        "product_id": task.product_id,
        "asin": product.asin if product else None,
        "title": product.title if product else "Unknown product",
        "source_location_id": task.source_location_id,
        "destination_location_id": task.destination_location_id,
        "qty": task.qty,
        "actual_qty": task.actual_qty,
        "status": task.status,
        "trigger": task.trigger,
        "priority": task.priority,
        "source_ref": task.source_ref,
        "assigned_user_id": task.assigned_user_id,
        "assigned_by_user_id": task.assigned_by_user_id,
        "version": task.version,
        "source_available_qty": (
            max(0, source_balance.qty_on_hand - source_balance.qty_reserved)
            if source_balance else 0
        ),
        "destination_on_hand": destination_balance.qty_on_hand if destination_balance else 0,
        "claimed_at": task.claimed_at.isoformat() if task.claimed_at else None,
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "source_scanned_at": task.source_scanned_at.isoformat() if task.source_scanned_at else None,
        "destination_scanned_at": task.destination_scanned_at.isoformat() if task.destination_scanned_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "failure_reason": task.failure_reason,
        "created_at": task.created_at.isoformat(),
    }


def queue(
    db: Session,
    *,
    status: str | None = None,
    assigned_user_id: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    query = select(ReplenishmentTask)
    if status:
        query = query.where(ReplenishmentTask.status == status.strip().upper())
    else:
        query = query.where(ReplenishmentTask.status.not_in(TERMINAL_STATUSES))
    if assigned_user_id:
        query = query.where(ReplenishmentTask.assigned_user_id == assigned_user_id)
    rows = db.scalars(
        query.order_by(ReplenishmentTask.priority.desc(), ReplenishmentTask.created_at.asc()).limit(limit)
    ).all()
    return [task_payload(db, row) for row in rows]


def assign(
    db: Session,
    *,
    task: ReplenishmentTask,
    user_id: str,
    manager_id: str,
    priority: int | None = None,
) -> ReplenishmentTask:
    if task.status not in {"READY", "ASSIGNED"}:
        raise ReplenishmentError(f"Task cannot be assigned from {task.status}", "INVALID_STATE")
    _ensure_available_worker(db, user_id)
    if task.assigned_user_id and task.assigned_user_id != user_id:
        raise ReplenishmentError("Task is already assigned", "ALREADY_ASSIGNED")
    task.assigned_user_id = user_id
    task.assigned_by_user_id = manager_id
    task.status = "ASSIGNED"
    if priority is not None:
        task.priority = max(0, min(1000, priority))
    task.version += 1
    db.flush()
    return task


def claim(
    db: Session,
    *,
    task: ReplenishmentTask,
    user_id: str,
    device_id: str | None,
) -> ReplenishmentTask:
    if task.status not in {"READY", "ASSIGNED"}:
        if task.assigned_user_id == user_id and task.status in EXECUTABLE_STATUSES:
            return task
        raise ReplenishmentError(f"Task cannot be claimed from {task.status}", "INVALID_STATE")
    _ensure_available_worker(db, user_id)
    if task.assigned_user_id and task.assigned_user_id != user_id:
        raise ReplenishmentError("Task belongs to another worker", "OWNERSHIP_MISMATCH")
    task.assigned_user_id = user_id
    task.status = "CLAIMED"
    task.claimed_at = task.claimed_at or _now()
    task.version += 1
    try:
        set_worker_state(
            db,
            user_id,
            "REPLENISHING",
            activity_ref=task.id,
            reason="REPLENISHMENT_CLAIMED",
        )
    except OpsError as exc:
        raise ReplenishmentError(str(exc), exc.code) from exc
    _event(
        db,
        event_id=f"claim:{task.id}:{task.version}",
        task=task,
        user_id=user_id,
        device_id=device_id,
        event_type="CLAIM",
    )
    db.flush()
    return task


def scan_source(
    db: Session,
    *,
    task: ReplenishmentTask,
    event_id: str,
    user_id: str,
    device_id: str | None,
    source_location_id: str,
) -> dict[str, Any]:
    _require_owner(task, user_id)
    if task.status not in {"CLAIMED", "STARTED", "SOURCE_CONFIRMED"}:
        raise ReplenishmentError(f"Source cannot be scanned from {task.status}", "INVALID_STATE")
    if source_location_id.strip().upper() != task.source_location_id.upper():
        raise ReplenishmentError(
            f"Wrong source bin: expected {task.source_location_id}",
            "SOURCE_LOCATION_MISMATCH",
        )
    _, duplicate = _event(
        db,
        event_id=event_id,
        task=task,
        user_id=user_id,
        device_id=device_id,
        event_type="SOURCE_SCAN",
        source_location_id=task.source_location_id,
    )
    if not duplicate:
        task.status = "SOURCE_CONFIRMED"
        task.started_at = task.started_at or _now()
        task.source_scanned_at = _now()
        task.version += 1
    db.flush()
    return {"duplicate": duplicate, "task": task_payload(db, task)}


def confirm_item(
    db: Session,
    *,
    task: ReplenishmentTask,
    event_id: str,
    user_id: str,
    device_id: str | None,
    barcode: str,
) -> dict[str, Any]:
    _require_owner(task, user_id)
    if task.status not in {"SOURCE_CONFIRMED", "STARTED"}:
        raise ReplenishmentError("Scan the source bin first", "SOURCE_NOT_CONFIRMED")
    mapping = db.scalar(select(Barcode).where(Barcode.code == barcode.strip()))
    if mapping is None or mapping.product_id != task.product_id:
        raise ReplenishmentError("Wrong product barcode", "PRODUCT_MISMATCH")
    _, duplicate = _event(
        db,
        event_id=event_id,
        task=task,
        user_id=user_id,
        device_id=device_id,
        event_type="ITEM_SCAN",
        source_location_id=task.source_location_id,
        payload={"barcode": barcode.strip()},
    )
    if not duplicate:
        task.status = "STARTED"
        task.started_at = task.started_at or _now()
        task.version += 1
    db.flush()
    return {"duplicate": duplicate, "task": task_payload(db, task)}


def scan_destination(
    db: Session,
    *,
    task: ReplenishmentTask,
    event_id: str,
    user_id: str,
    device_id: str | None,
    destination_location_id: str,
) -> dict[str, Any]:
    _require_owner(task, user_id)
    if task.status not in {"STARTED", "SOURCE_CONFIRMED", "DESTINATION_CONFIRMED"}:
        raise ReplenishmentError(f"Destination cannot be scanned from {task.status}", "INVALID_STATE")
    if destination_location_id.strip().upper() != task.destination_location_id.upper():
        raise ReplenishmentError(
            f"Wrong destination bin: expected {task.destination_location_id}",
            "DESTINATION_LOCATION_MISMATCH",
        )
    product = db.get(Product, task.product_id)
    destination = db.get(Location, task.destination_location_id)
    if product is None or destination is None:
        raise ReplenishmentError("Product or destination is missing", "NOT_FOUND")
    compatible, code = storage_compatible(product, destination)
    if not compatible:
        raise ReplenishmentError(f"Destination is incompatible: {code}", code or "INCOMPATIBLE")

    _, duplicate = _event(
        db,
        event_id=event_id,
        task=task,
        user_id=user_id,
        device_id=device_id,
        event_type="DESTINATION_SCAN",
        destination_location_id=task.destination_location_id,
    )
    if not duplicate:
        task.status = "DESTINATION_CONFIRMED"
        task.destination_scanned_at = _now()
        task.version += 1
    db.flush()
    return {"duplicate": duplicate, "task": task_payload(db, task)}


def complete(
    db: Session,
    *,
    task: ReplenishmentTask,
    event_id: str,
    user_id: str,
    device_id: str | None,
    actual_qty: int,
) -> dict[str, Any]:
    _require_owner(task, user_id)
    if task.status != "DESTINATION_CONFIRMED":
        raise ReplenishmentError("Source, item and destination scans are required", "SCANS_INCOMPLETE")
    if actual_qty <= 0 or actual_qty > task.qty:
        raise ReplenishmentError("Actual quantity must be between 1 and planned quantity", "BAD_QUANTITY")

    existing = db.scalar(select(ReplenishmentEvent).where(ReplenishmentEvent.event_id == event_id))
    if existing:
        return {"duplicate": True, "task": task_payload(db, task)}

    try:
        movement = move_inventory(
            db,
            event_id=f"replenishment:{event_id}",
            product_id=task.product_id,
            qty=actual_qty,
            source_location_id=task.source_location_id,
            destination_location_id=task.destination_location_id,
            reason="REPLENISHMENT",
            task_id=task.id,
            user_id=user_id,
            device_id=device_id,
        )
    except InventoryError as exc:
        raise ReplenishmentError(str(exc), "INVENTORY_CONFLICT") from exc

    _event(
        db,
        event_id=event_id,
        task=task,
        user_id=user_id,
        device_id=device_id,
        event_type="COMPLETE",
        qty=actual_qty,
        source_location_id=task.source_location_id,
        destination_location_id=task.destination_location_id,
        payload={"movement_id": movement.movement.id},
    )
    task.actual_qty = actual_qty
    task.completed_at = _now()
    task.status = "COMPLETED" if actual_qty == task.qty else "PARTIAL"
    task.version += 1

    remainder = None
    if actual_qty < task.qty:
        remainder = ReplenishmentTask(
            product_id=task.product_id,
            source_location_id=task.source_location_id,
            destination_location_id=task.destination_location_id,
            qty=task.qty - actual_qty,
            status="READY",
            trigger="PARTIAL_REPLENISHMENT",
            source_ref=task.id,
            priority=max(task.priority, 70),
        )
        db.add(remainder)

    state = get_worker_state(db, user_id, create=False)
    if state and state.activity_ref == task.id:
        set_worker_state(db, user_id, "AVAILABLE", reason="REPLENISHMENT_COMPLETED", force=True)
    db.flush()
    return {
        "duplicate": False,
        "task": task_payload(db, task),
        "remainder_task_id": remainder.id if remainder else None,
    }


def cancel(
    db: Session,
    *,
    task: ReplenishmentTask,
    manager_id: str,
    reason: str,
) -> ReplenishmentTask:
    if task.status in TERMINAL_STATUSES:
        return task
    task.status = "CANCELLED"
    task.cancelled_at = _now()
    task.failure_reason = reason.strip()[:240]
    task.version += 1
    if task.assigned_user_id:
        state = get_worker_state(db, task.assigned_user_id, create=False)
        if state and state.activity_ref == task.id:
            set_worker_state(db, task.assigned_user_id, "AVAILABLE", reason="REPLENISHMENT_CANCELLED", force=True)
    _event(
        db,
        event_id=f"cancel:{task.id}:{task.version}",
        task=task,
        user_id=manager_id,
        device_id=None,
        event_type="CANCEL",
        payload={"reason": reason},
    )
    db.flush()
    return task


def _require_owner(task: ReplenishmentTask, user_id: str) -> None:
    if task.assigned_user_id != user_id:
        raise ReplenishmentError("Replenishment task belongs to another worker", "OWNERSHIP_MISMATCH")


def generate_candidates(
    db: Session,
    *,
    low_stock_threshold: int = 3,
    target_qty: int = 12,
    max_new_tasks: int = 100,
) -> list[ReplenishmentTask]:
    """Create proactive pick-face replenishments from non-pickable reserve stock."""

    destinations = db.scalars(
        select(Location).where(
            Location.active == True,  # noqa: E712
            Location.pickable == True,  # noqa: E712
            Location.sellable == True,  # noqa: E712
        )
    ).all()
    created: list[ReplenishmentTask] = []
    for destination in destinations:
        balances = db.scalars(
            select(InventoryBalance).where(InventoryBalance.location_id == destination.id)
        ).all()
        for dest_balance in balances:
            available_at_dest = max(0, dest_balance.qty_on_hand - dest_balance.qty_reserved)
            if available_at_dest > low_stock_threshold:
                continue
            active = db.scalar(
                select(ReplenishmentTask).where(
                    ReplenishmentTask.product_id == dest_balance.product_id,
                    ReplenishmentTask.destination_location_id == destination.id,
                    ReplenishmentTask.status.not_in(TERMINAL_STATUSES),
                )
            )
            if active:
                continue
            product = db.get(Product, dest_balance.product_id)
            if product is None:
                continue
            source_balances = db.scalars(
                select(InventoryBalance).where(
                    InventoryBalance.product_id == product.id,
                    InventoryBalance.location_id != destination.id,
                    (InventoryBalance.qty_on_hand - InventoryBalance.qty_reserved) > 0,
                )
            ).all()
            choices = []
            for source_balance in source_balances:
                source = db.get(Location, source_balance.location_id)
                if source is None or not source.active:
                    continue
                compatible, _ = storage_compatible(product, destination)
                if not compatible:
                    continue
                reserve_available = max(0, source_balance.qty_on_hand - source_balance.qty_reserved)
                choices.append((0 if not source.pickable else 1, -reserve_available, source, reserve_available))
            choices.sort(key=lambda row: (row[0], row[1], row[2].id))
            if not choices:
                continue
            _, _, source, reserve_available = choices[0]
            qty = min(max(1, target_qty - available_at_dest), reserve_available)
            task = ReplenishmentTask(
                product_id=product.id,
                source_location_id=source.id,
                destination_location_id=destination.id,
                qty=qty,
                status="READY",
                trigger="LOW_PICK_FACE_STOCK",
                priority=85 if available_at_dest == 0 else 60,
            )
            db.add(task)
            created.append(task)
            if len(created) >= max_new_tasks:
                db.flush()
                return created
    db.flush()
    return created
