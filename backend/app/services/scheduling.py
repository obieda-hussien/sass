from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Order, OrderStatus, PickTask, TaskStatus, User
from .picking import PickError, task_snapshot
from .ops_platform import release_pick_lease, worker_dispatch_status

OFFER_TTL_SECONDS = 30
TERMINAL_TASK_STATES = {
    TaskStatus.CANCELLED.value,
    TaskStatus.COMPLETED.value,
}
ACTIVE_TASK_STATES = {
    TaskStatus.OFFERED.value,
    TaskStatus.ACCEPTED.value,
    TaskStatus.PICKING.value,
    TaskStatus.PICKED.value,
    TaskStatus.PACK_RACK.value,
    TaskStatus.STAGED.value,
    TaskStatus.HANDOFF_READY.value,
    TaskStatus.HANDED_OFF.value,
    TaskStatus.RECOVERY_REQUIRED.value,
}


def _utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def active_task_for_actor(db: Session, user_id: str, device_id: str) -> PickTask | None:
    """Return the server-owned task the PDA must resume after app/device restart."""
    return db.scalar(
        select(PickTask)
        .where(
            PickTask.assigned_user_id == user_id,
            PickTask.status.in_(ACTIVE_TASK_STATES),
        )
        .order_by(PickTask.updated_at.desc())
        .limit(1)
    )


def _expire_stale_offers(db: Session, now: datetime) -> int:
    cutoff = now - timedelta(seconds=OFFER_TTL_SECONDS)
    stale = db.scalars(
        select(PickTask)
        .where(PickTask.status == TaskStatus.OFFERED.value, PickTask.offered_at <= cutoff)
        .with_for_update()
    ).all()
    for task in stale:
        task.status = TaskStatus.READY.value
        task.assigned_user_id = None
        task.assigned_device_id = None
        task.offered_at = None
        task.server_version += 1
        order = db.get(Order, task.order_id)
        if order and order.status == OrderStatus.OFFERED.value:
            order.status = OrderStatus.ALLOCATED.value
    return len(stale)


def claim_next_task(db: Session, user_id: str, device_id: str) -> dict | None:
    """Atomically resume an owned task or claim the next READY task for 30 seconds."""
    current = active_task_for_actor(db, user_id, device_id)
    if current is not None:
        snapshot = task_snapshot(db, current)
        snapshot["resumed"] = True
        snapshot["offer_expires_at"] = (
            (_utc(current.offered_at) + timedelta(seconds=OFFER_TTL_SECONDS)).isoformat()
            if current.status == TaskStatus.OFFERED.value and current.offered_at else None
        )
        return snapshot

    user = db.get(User, user_id)
    if user is None:
        raise PickError("Associate not found", "WORKER_NOT_FOUND")
    dispatch = worker_dispatch_status(db, user)
    if not dispatch["dispatchable"]:
        raise PickError(
            "Picker is not available: " + ", ".join(dispatch["reasons"]),
            "PICKER_NOT_ELIGIBLE",
        )

    now = datetime.now(timezone.utc)
    _expire_stale_offers(db, now)

    task = db.scalar(
        select(PickTask)
        .join(Order, Order.id == PickTask.order_id)
        .where(PickTask.status == TaskStatus.READY.value)
        .order_by(Order.priority.asc(), Order.created_at.asc(), PickTask.id.asc())
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if task is None:
        return None

    task.assigned_user_id = user_id
    task.assigned_device_id = device_id
    task.status = TaskStatus.OFFERED.value
    task.offered_at = now
    task.server_version += 1
    order = db.get(Order, task.order_id)
    if order:
        order.status = OrderStatus.OFFERED.value
    db.flush()

    snapshot = task_snapshot(db, task)
    snapshot["resumed"] = False
    snapshot["offer_expires_at"] = (now + timedelta(seconds=OFFER_TTL_SECONDS)).isoformat()
    return snapshot


def reject_offer(db: Session, task: PickTask, user_id: str, device_id: str, reason: str) -> dict:
    if task.status != TaskStatus.OFFERED.value:
        raise PickError(f"Task cannot be rejected from {task.status}", "INVALID_STATE")
    if task.assigned_user_id != user_id or task.assigned_device_id != device_id:
        raise PickError("Associate/device does not own this offer", "OWNERSHIP_MISMATCH")

    task.status = TaskStatus.READY.value
    task.assigned_user_id = None
    task.assigned_device_id = None
    task.offered_at = None
    task.server_version += 1
    release_pick_lease(db, task, reason="OFFER_REJECTED")
    order = db.get(Order, task.order_id)
    if order and order.status == OrderStatus.OFFERED.value:
        order.status = OrderStatus.ALLOCATED.value
    db.flush()
    return {
        "task_id": task.id,
        "status": task.status,
        "reason": reason,
        "server_version": task.server_version,
    }
