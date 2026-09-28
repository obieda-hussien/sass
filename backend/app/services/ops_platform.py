from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session

from ..models import (
    AttendanceEntry,
    Device,
    EmployeeProfile,
    InventoryBalance,
    Location,
    Order,
    OrderLine,
    OrderStatus,
    PerformanceEvent,
    PickTask,
    PickTaskItem,
    Product,
    ScanEvent,
    TaskStatus,
    User,
)
from ..models_ops import (
    ActivePickLease,
    AttendanceComputation,
    DeviceTelemetry,
    FulfillmentHold,
    InventoryAlert,
    InventoryLot,
    OrderBag,
    OperationalIncident,
    PayrollPolicy,
    PickException,
    PickOffer,
    ReceivingSession,
    ReplenishmentTask,
    Shipment,
    ShipmentLine,
    ShiftSession,
    StowTask,
    WorkerQualification,
    WorkerRuntimeState,
    WorkerStateEvent,
)
from .compatibility import storage_compatible
from .eventing import enqueue_outbox
from .inventory import InventoryError, move_inventory
from .ops_optimization import (
    destination_has_capacity,
    distance_to_task_first_item,
    evaluate_guard_rules,
    worker_domain_reasons,
)


PDA_PRESENCE_TTL_SECONDS = 20

ACTIVE_PICK_STATES = {
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

DISPATCH_BLOCKING_STATES = {
    "OFFLINE",
    "ORDER_ASSIGNED",
    "PICKING",
    "BREAK",
    "DOCK_CHECK_IN",
    "RECEIVING",
    "RECEIVING_AMBIENT",
    "RECEIVING_CHILLED",
    "RECEIVING_FROZEN",
    "RECEIVING_HAZ",
    "RECEIVING_HRV",
    "RECEIVING_PRODUCE",
    "OPENING_SHIPMENT",
    "STOWING",
    "BOH_MOVE",
    "REPLENISHING",
    "UNPACKING",
    "CYCLE_COUNT",
    "EXPIRY_AUDIT",
    "BIN_CHECK",
    "VENDOR_REMOVAL",
    "TRAINING",
    "ENDING_SHIFT",
}

PICKER_ROLES = {"PICKER", "SENIOR_PICKER"}
VALID_HOLD_SCOPES = {"SITE", "DOMAIN", "ZONE", "AISLE", "BIN", "SKU"}
SHIPMENT_DOMAINS = {"AMBIENT", "CHILLED", "FROZEN", "HAZ", "HRV", "PRODUCE"}


class OpsError(RuntimeError):
    def __init__(self, message: str, code: str = "OPS_ERROR"):
        super().__init__(message)
        self.code = code


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def domain_for_location(location: Location) -> str:
    if location.handling_class in {"HAZ", "HRV"}:
        return location.handling_class
    if location.fixture_type == "V":
        return "PRODUCE"
    return location.temperature_class or "AMBIENT"


def route_sort_key(location: Location) -> tuple:
    """Warm path first, then chilled and frozen, without warm/cold ping-pong."""
    cold_group = {
        "AMBIENT": 0,
        "PRODUCE": 0,
        "HAZ": 0,
        "HRV": 0,
        "CHILLED": 1,
        "FROZEN": 2,
    }.get(domain_for_location(location), 0)
    return (
        cold_group,
        location.aisle if location.aisle is not None else 9999,
        location.level or "Z",
        location.slot if location.slot is not None else 9999,
        location.id,
    )


def candidate_inventory_sort_key(db: Session, product: Product, location: Location) -> tuple:
    """FEFO chooses the oldest sellable lot first; route ordering happens after allocation."""
    earliest = db.scalar(
        select(func.min(InventoryLot.expires_on)).where(
            InventoryLot.product_id == product.id,
            InventoryLot.location_id == location.id,
            InventoryLot.qty > 0,
            InventoryLot.expires_on.is_not(None),
        )
    )
    expiry_rank = earliest.toordinal() if isinstance(earliest, date) else 99_999_999
    return (expiry_rank, *route_sort_key(location))


def get_worker_state(db: Session, user_id: str, *, create: bool = True) -> WorkerRuntimeState | None:
    state = db.get(WorkerRuntimeState, user_id)
    if state is None and create:
        user = db.get(User, user_id)
        if user is None:
            raise OpsError("Worker not found", "WORKER_NOT_FOUND")
        state = WorkerRuntimeState(user_id=user_id, state="AVAILABLE" if user.active else "OFFLINE")
        db.add(state)
        db.flush()
    return state


def _active_pick_for_user(db: Session, user_id: str) -> PickTask | None:
    return db.scalar(
        select(PickTask)
        .where(
            PickTask.assigned_user_id == user_id,
            PickTask.status.in_(ACTIVE_PICK_STATES),
        )
        .order_by(PickTask.updated_at.desc())
        .limit(1)
    )


def set_worker_state(
    db: Session,
    user_id: str,
    new_state: str,
    *,
    activity_ref: str | None = None,
    reason: str | None = None,
    force: bool = False,
) -> WorkerRuntimeState:
    normalized = new_state.strip().upper()
    state = get_worker_state(db, user_id, create=True)
    assert state is not None

    lease = db.get(ActivePickLease, user_id)
    if lease and normalized not in {"ORDER_ASSIGNED", "PICKING"} and not force:
        raise OpsError("Worker has an active pick order", "ACTIVE_PICK_EXISTS")

    previous = state.state
    state.state = normalized
    state.activity_ref = activity_ref
    state.reason = reason
    state.updated_at = now_utc()
    event = WorkerStateEvent(
        user_id=user_id,
        from_state=previous,
        to_state=normalized,
        activity_ref=activity_ref,
        reason=reason,
    )
    db.add(event)
    db.flush()
    enqueue_outbox(
        db,
        topic="worker.state.changed",
        aggregate_type="USER",
        aggregate_id=user_id,
        payload={
            "worker_state_event_id": event.id,
            "from_state": previous,
            "to_state": normalized,
            "activity_ref": activity_ref,
            "reason": reason,
            "occurred_at": event.created_at,
        },
    )
    return state


def worker_qualifications(db: Session, user_id: str) -> set[str]:
    rows = db.scalars(
        select(WorkerQualification).where(
            WorkerQualification.user_id == user_id,
            WorkerQualification.active == True,  # noqa: E712
        )
    ).all()
    return {row.qualification.upper() for row in rows}


def task_required_qualifications(db: Session, task: PickTask) -> set[str]:
    requirements: set[str] = set()
    items = db.scalars(select(PickTaskItem).where(PickTaskItem.task_id == task.id)).all()
    for item in items:
        product = db.get(Product, item.product_id)
        if product and product.handling_class in {"HAZ", "HRV"}:
            requirements.add(product.handling_class)
    return requirements


def worker_dispatch_status(db: Session, user: User, task: PickTask | None = None) -> dict[str, Any]:
    state = get_worker_state(db, user.id, create=True)
    lease = db.get(ActivePickLease, user.id)
    active_task = _active_pick_for_user(db, user.id)
    reasons: list[str] = []

    if not user.active:
        reasons.append("USER_INACTIVE")
    if user.role.upper() not in PICKER_ROLES:
        reasons.append("NOT_PICKER")

    latest_device = db.scalar(
        select(Device)
        .where(Device.last_user_id == user.id)
        .order_by(Device.last_seen_at.desc())
        .limit(1)
    )
    live_cutoff = now_utc() - timedelta(seconds=PDA_PRESENCE_TTL_SECONDS)
    if latest_device is None or latest_device.last_seen_at is None:
        reasons.append("PDA_NOT_CONNECTED")
    else:
        last_seen = latest_device.last_seen_at
        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=timezone.utc)
        if latest_device.status != "ONLINE" or last_seen < live_cutoff:
            reasons.append("PDA_OFFLINE_OR_STALE")
    if state and state.state != "AVAILABLE":
        # A direct assignment reserves the worker for that exact task.
        if not (
            task
            and state.state == "ORDER_ASSIGNED"
            and state.activity_ref == task.id
            and active_task
            and active_task.id == task.id
        ):
            reasons.append(f"STATE_{state.state}")
    if lease and (task is None or lease.task_id != task.id):
        reasons.append("ACTIVE_PICK_EXISTS")
    if active_task and (task is None or active_task.id != task.id):
        reasons.append("ACTIVE_PICK_EXISTS")

    required = task_required_qualifications(db, task) if task else set()
    missing = sorted(required - worker_qualifications(db, user.id))
    reasons.extend(f"MISSING_{value}_QUALIFICATION" for value in missing)
    reasons.extend(worker_domain_reasons(db, user.id, task))
    estimated_walk = distance_to_task_first_item(db, task, user.id) if task else None

    return {
        "user_id": user.id,
        "username": user.username,
        "state": state.state if state else "OFFLINE",
        "activity_ref": state.activity_ref if state else None,
        "dispatchable": not reasons,
        "reasons": sorted(set(reasons)),
        "required_qualifications": sorted(required),
        "qualifications": sorted(worker_qualifications(db, user.id)),
        "active_task_id": active_task.id if active_task else None,
        "estimated_walk_to_first_item_m": estimated_walk,
        "device_id": latest_device.id if latest_device else None,
        "device_last_seen_at": latest_device.last_seen_at.isoformat() if latest_device and latest_device.last_seen_at else None,
        "device_live": not any(reason in {"PDA_NOT_CONNECTED", "PDA_OFFLINE_OR_STALE"} for reason in reasons),
    }


def eligible_workers_for_task(db: Session, task: PickTask) -> list[dict[str, Any]]:
    users = db.scalars(
        select(User).where(User.active == True, User.role.in_(PICKER_ROLES)).order_by(User.username)  # noqa: E712
    ).all()
    return [status for user in users if (status := worker_dispatch_status(db, user, task))["dispatchable"]]


def broadcast_task(db: Session, task: PickTask, *, ttl_seconds: int = 90) -> dict[str, Any]:
    if task.status not in {TaskStatus.READY.value, TaskStatus.OFFERED.value}:
        raise OpsError(f"Task cannot be broadcast from {task.status}", "INVALID_TASK_STATE")
    if task.assigned_user_id:
        raise OpsError("Task is already assigned", "TASK_ALREADY_ASSIGNED")

    recipients = eligible_workers_for_task(db, task)
    expires = now_utc() + timedelta(seconds=max(10, ttl_seconds))
    for worker in recipients:
        existing = db.scalar(
            select(PickOffer).where(PickOffer.task_id == task.id, PickOffer.user_id == worker["user_id"])
        )
        if existing:
            existing.status = "OPEN"
            existing.offered_at = now_utc()
            existing.expires_at = expires
            existing.closed_at = None
        else:
            db.add(PickOffer(
                task_id=task.id,
                user_id=worker["user_id"],
                status="OPEN",
                expires_at=expires,
            ))

    if recipients:
        task.status = TaskStatus.OFFERED.value
        task.offered_at = now_utc()
        task.server_version += 1
        order = db.get(Order, task.order_id)
        if order:
            order.status = OrderStatus.OFFERED.value
    db.flush()
    return {
        "task_id": task.id,
        "offered_to": len(recipients),
        "expires_at": expires.isoformat(),
        "workers": recipients,
    }


def my_open_offers(db: Session, user_id: str) -> list[PickOffer]:
    now = now_utc()

    # Close stale offers first.
    existing_offers = db.scalars(
        select(PickOffer)
        .where(PickOffer.user_id == user_id, PickOffer.status == "OPEN")
        .order_by(PickOffer.offered_at)
    ).all()
    for offer in existing_offers:
        if offer.expires_at and _utc(offer.expires_at) <= now:
            offer.status = "EXPIRED"
            offer.closed_at = now

    # A picker may come online after an order was originally broadcast. Polling
    # the waiting queue therefore backfills an offer for currently eligible,
    # unowned READY/OFFERED work instead of requiring a manual refresh/rebroadcast.
    user = db.get(User, user_id)
    if user is not None and worker_dispatch_status(db, user)["dispatchable"]:
        candidates = db.execute(
            select(PickTask, Order)
            .join(Order, Order.id == PickTask.order_id)
            .where(
                PickTask.assigned_user_id.is_(None),
                PickTask.status.in_([TaskStatus.READY.value, TaskStatus.OFFERED.value]),
            )
            .order_by(Order.priority.desc(), Order.created_at.asc())
            .limit(20)
        ).all()
        for task, order in candidates:
            if not worker_dispatch_status(db, user, task)["dispatchable"]:
                continue
            offer = db.scalar(
                select(PickOffer).where(
                    PickOffer.task_id == task.id,
                    PickOffer.user_id == user_id,
                )
            )
            if offer is None:
                offer = PickOffer(
                    task_id=task.id,
                    user_id=user_id,
                    status="OPEN",
                    offered_at=now,
                    expires_at=now + timedelta(seconds=90),
                )
                db.add(offer)
            elif offer.status != "OPEN" or (
                offer.expires_at is not None and _utc(offer.expires_at) <= now
            ):
                offer.status = "OPEN"
                offer.offered_at = now
                offer.expires_at = now + timedelta(seconds=90)
                offer.closed_at = None

            if task.status == TaskStatus.READY.value:
                task.status = TaskStatus.OFFERED.value
                task.offered_at = now
                task.server_version += 1
                order.status = OrderStatus.OFFERED.value

    db.flush()
    return db.scalars(
        select(PickOffer)
        .where(
            PickOffer.user_id == user_id,
            PickOffer.status == "OPEN",
            or_(PickOffer.expires_at.is_(None), PickOffer.expires_at > now),
        )
        .order_by(PickOffer.offered_at)
    ).all()

def _acquire_lease(
    db: Session,
    *,
    user_id: str,
    task_id: str,
    device_id: str | None,
    mode: str,
) -> ActivePickLease:
    existing = db.get(ActivePickLease, user_id)
    if existing:
        if existing.task_id == task_id:
            if device_id and not existing.device_id:
                existing.device_id = device_id
            return existing
        raise OpsError("Picker already has another active order", "ACTIVE_PICK_EXISTS")

    other = db.scalar(select(ActivePickLease).where(ActivePickLease.task_id == task_id))
    if other:
        raise OpsError("Order was already claimed by another picker", "ORDER_ALREADY_CLAIMED")

    lease = ActivePickLease(user_id=user_id, task_id=task_id, device_id=device_id, mode=mode)
    db.add(lease)
    db.flush()
    return lease


def acquire_pick_lease(
    db: Session,
    *,
    user_id: str,
    task_id: str,
    device_id: str | None,
    mode: str = "CLAIM",
) -> ActivePickLease:
    return _acquire_lease(
        db,
        user_id=user_id,
        task_id=task_id,
        device_id=device_id,
        mode=mode,
    )


def claim_task(db: Session, task: PickTask, user_id: str, device_id: str) -> PickTask:
    user = db.get(User, user_id)
    if not user:
        raise OpsError("Worker not found", "WORKER_NOT_FOUND")

    if task.assigned_user_id and task.assigned_user_id != user_id:
        raise OpsError("Order was already claimed by another picker", "ORDER_ALREADY_CLAIMED")

    direct_for_user = task.assigned_user_id == user_id
    status = worker_dispatch_status(db, user, task if direct_for_user else None)
    if not status["dispatchable"]:
        raise OpsError("Picker is not available: " + ", ".join(status["reasons"]), "PICKER_NOT_ELIGIBLE")

    open_offers = db.scalars(
        select(PickOffer).where(PickOffer.task_id == task.id, PickOffer.status == "OPEN")
    ).all()
    if open_offers and not direct_for_user and not any(o.user_id == user_id for o in open_offers):
        raise OpsError("This order was not offered to the picker", "OFFER_NOT_FOUND")

    if task.status not in {TaskStatus.READY.value, TaskStatus.OFFERED.value}:
        if task.assigned_user_id == user_id and task.status in {TaskStatus.ACCEPTED.value, TaskStatus.PICKING.value}:
            _acquire_lease(db, user_id=user_id, task_id=task.id, device_id=device_id, mode="RESUME")
            return task
        raise OpsError(f"Task cannot be claimed from {task.status}", "INVALID_TASK_STATE")

    # The compare-and-set on assigned_user_id is the winner decision. A stale
    # client that loses the race updates zero rows and cannot own the order.
    if task.assigned_user_id is None:
        result = db.execute(
            update(PickTask)
            .where(
                PickTask.id == task.id,
                PickTask.assigned_user_id.is_(None),
                PickTask.status.in_([TaskStatus.READY.value, TaskStatus.OFFERED.value]),
            )
            .values(
                assigned_user_id=user_id,
                assigned_device_id=device_id,
                status=TaskStatus.ACCEPTED.value,
                accepted_at=now_utc(),
                server_version=PickTask.server_version + 1,
            )
        )
        if result.rowcount != 1:
            raise OpsError("Order was already claimed by another picker", "ORDER_ALREADY_CLAIMED")
    else:
        task.assigned_device_id = device_id
        task.status = TaskStatus.ACCEPTED.value
        task.accepted_at = task.accepted_at or now_utc()
        task.server_version += 1

    _acquire_lease(db, user_id=user_id, task_id=task.id, device_id=device_id, mode="CLAIM")
    set_worker_state(db, user_id, "PICKING", activity_ref=task.id, reason="ORDER_CLAIMED", force=True)

    now = now_utc()
    offers = db.scalars(select(PickOffer).where(PickOffer.task_id == task.id)).all()
    for offer in offers:
        offer.status = "CLAIMED" if offer.user_id == user_id else "CLOSED"
        offer.closed_at = now

    order = db.get(Order, task.order_id)
    if order:
        order.status = OrderStatus.PICKING.value
    db.flush()
    enqueue_outbox(
        db,
        topic="order.claimed",
        aggregate_type="PICK_TASK",
        aggregate_id=task.id,
        payload={
            "task_id": task.id,
            "order_id": task.order_id,
            "user_id": user_id,
            "device_id": device_id,
            "claimed_at": now,
        },
    )
    db.expire(task)
    return db.get(PickTask, task.id)


def decline_task_offer(
    db: Session,
    task: PickTask,
    *,
    user_id: str,
    device_id: str | None = None,
    reason: str = "ASSOCIATE_REJECTED",
) -> dict[str, Any]:
    now = now_utc()

    # Direct/manual/legacy assignment: release the reserved picker and return
    # the order to the pool.
    if task.assigned_user_id is not None:
        if task.assigned_user_id != user_id:
            raise OpsError("Order is assigned to another picker", "OWNERSHIP_MISMATCH")
        if task.assigned_device_id and device_id and task.assigned_device_id != device_id:
            raise OpsError("Order belongs to another device", "DEVICE_MISMATCH")
        if task.status != TaskStatus.OFFERED.value:
            raise OpsError(f"Task cannot be rejected from {task.status}", "INVALID_TASK_STATE")
        release_pick_lease(db, task, reason="OFFER_REJECTED")
        task.assigned_user_id = None
        task.assigned_device_id = None
        task.status = TaskStatus.READY.value
        task.offered_at = None
        task.server_version += 1
        order = db.get(Order, task.order_id)
        if order and order.status == OrderStatus.OFFERED.value:
            order.status = OrderStatus.ALLOCATED.value
        db.flush()
        return {"task_id": task.id, "status": task.status, "reason": reason}

    offer = db.scalar(
        select(PickOffer).where(
            PickOffer.task_id == task.id,
            PickOffer.user_id == user_id,
            PickOffer.status == "OPEN",
        )
    )
    if offer is None:
        raise OpsError("Open offer not found for picker", "OFFER_NOT_FOUND")
    offer.status = "DECLINED"
    offer.closed_at = now

    open_count = db.scalar(
        select(func.count()).select_from(PickOffer).where(
            PickOffer.task_id == task.id,
            PickOffer.status == "OPEN",
            or_(PickOffer.expires_at.is_(None), PickOffer.expires_at > now),
        )
    ) or 0
    if open_count == 0 and task.status == TaskStatus.OFFERED.value:
        task.status = TaskStatus.READY.value
        task.offered_at = None
        task.server_version += 1
        order = db.get(Order, task.order_id)
        if order and order.status == OrderStatus.OFFERED.value:
            order.status = OrderStatus.ALLOCATED.value

    db.flush()
    return {
        "task_id": task.id,
        "status": task.status,
        "offer_status": offer.status,
        "reason": reason,
    }


def direct_assign_task(
    db: Session,
    task: PickTask,
    *,
    user_id: str,
    manager_id: str,
    device_id: str | None = None,
    reason: str = "MANUAL_DISPATCH",
) -> PickTask:
    user = db.get(User, user_id)
    if not user:
        raise OpsError("Worker not found", "WORKER_NOT_FOUND")
    status = worker_dispatch_status(db, user, task)
    if not status["dispatchable"]:
        raise OpsError("Picker is not available: " + ", ".join(status["reasons"]), "PICKER_NOT_ELIGIBLE")
    if task.status not in {TaskStatus.READY.value, TaskStatus.OFFERED.value} or task.assigned_user_id:
        raise OpsError("Task is no longer available", "TASK_NOT_AVAILABLE")

    result = db.execute(
        update(PickTask)
        .where(
            PickTask.id == task.id,
            PickTask.assigned_user_id.is_(None),
            PickTask.status.in_([TaskStatus.READY.value, TaskStatus.OFFERED.value]),
        )
        .values(
            assigned_user_id=user_id,
            assigned_device_id=device_id,
            status=TaskStatus.OFFERED.value,
            offered_at=now_utc(),
            server_version=PickTask.server_version + 1,
        )
    )
    if result.rowcount != 1:
        raise OpsError("Task was claimed while assigning it", "TASK_NOT_AVAILABLE")

    _acquire_lease(db, user_id=user_id, task_id=task.id, device_id=device_id, mode="DIRECT_ASSIGN")
    set_worker_state(db, user_id, "ORDER_ASSIGNED", activity_ref=task.id, reason=reason, force=True)

    for offer in db.scalars(select(PickOffer).where(PickOffer.task_id == task.id)).all():
        offer.status = "CLOSED"
        offer.closed_at = now_utc()

    order = db.get(Order, task.order_id)
    if order:
        order.status = OrderStatus.OFFERED.value
    db.flush()
    db.expire(task)
    return db.get(PickTask, task.id)


def release_pick_lease(db: Session, task: PickTask, *, reason: str = "PICK_SESSION_FINISHED") -> None:
    if not task.assigned_user_id:
        return
    lease = db.get(ActivePickLease, task.assigned_user_id)
    if lease and lease.task_id == task.id:
        db.delete(lease)
    state = get_worker_state(db, task.assigned_user_id, create=False)
    if state and state.activity_ref == task.id and state.state in {"PICKING", "ORDER_ASSIGNED"}:
        set_worker_state(db, task.assigned_user_id, "AVAILABLE", reason=reason, force=True)
    db.flush()


def finalize_pick_session(db: Session, task: PickTask, user_id: str) -> dict[str, Any]:
    if task.assigned_user_id != user_id:
        raise OpsError("Picker does not own this order", "OWNERSHIP_MISMATCH")
    if task.status != TaskStatus.PICKED.value:
        raise OpsError(f"Order is not ready to finalize from {task.status}", "INVALID_TASK_STATE")
    bags = db.scalars(select(OrderBag).where(OrderBag.task_id == task.id)).all()
    if task.expected_units > 0 and not bags:
        raise OpsError("At least one bag/SPOO must be closed before finishing", "BAG_REQUIRED")
    release_pick_lease(db, task)
    return order_completion_summary(db, task.order_id)


def close_order_bag(db: Session, task: PickTask, user_id: str, spoo_code: str) -> OrderBag:
    if task.assigned_user_id != user_id:
        raise OpsError("Picker does not own this order", "OWNERSHIP_MISMATCH")
    if task.status not in {TaskStatus.ACCEPTED.value, TaskStatus.PICKING.value, TaskStatus.PICKED.value}:
        raise OpsError("Order is not in a baggable state", "INVALID_TASK_STATE")

    normalized = spoo_code.strip().upper()
    if len(normalized) < 4:
        raise OpsError("SPOO/barcode is too short", "BAD_SPOO")
    existing = db.scalar(select(OrderBag).where(OrderBag.spoo_code == normalized))
    if existing:
        if existing.task_id == task.id:
            return existing
        raise OpsError("SPOO is already attached to another order", "SPOO_IN_USE")

    max_bag = db.scalar(select(func.max(OrderBag.bag_no)).where(OrderBag.order_id == task.order_id)) or 0
    bag = OrderBag(
        order_id=task.order_id,
        task_id=task.id,
        bag_no=int(max_bag) + 1,
        spoo_code=normalized,
        closed_by_user_id=user_id,
    )
    db.add(bag)
    db.flush()
    return bag


def masked_spoo(code: str) -> str:
    suffix = code[-4:] if len(code) >= 4 else code
    return f"••••{suffix}"


def order_completion_summary(db: Session, order_id: str) -> dict[str, Any]:
    order = db.get(Order, order_id)
    if not order:
        raise OpsError("Order not found", "ORDER_NOT_FOUND")
    task = db.scalar(select(PickTask).where(PickTask.order_id == order_id))
    lines = db.scalars(select(OrderLine).where(OrderLine.order_id == order_id)).all()
    bags = db.scalars(select(OrderBag).where(OrderBag.order_id == order_id).order_by(OrderBag.bag_no)).all()
    user = db.get(User, task.assigned_user_id) if task and task.assigned_user_id else None

    items = []
    for line in lines:
        product = db.get(Product, line.product_id)
        items.append({
            "product_id": line.product_id,
            "asin": product.asin if product else None,
            "title": product.title if product else "Unknown product",
            "requested_qty": line.requested_qty,
            "picked_qty": line.picked_qty,
            "shorted_qty": line.shorted_qty,
        })

    return {
        "order_id": order.id,
        "external_ref": order.external_ref,
        "status": order.status,
        "picker": None if user is None else {"user_id": user.id, "username": user.username},
        "created_at": order.created_at.isoformat(),
        "pick_started_at": task.started_at.isoformat() if task and task.started_at else None,
        "pick_finished_at": task.finished_at.isoformat() if task and task.finished_at else None,
        "items": items,
        "sku_count": len(items),
        "requested_units": sum(x["requested_qty"] for x in items),
        "picked_units": sum(x["picked_qty"] for x in items),
        "shorted_units": sum(x["shorted_qty"] for x in items),
        "bag_count": len(bags),
        "bags": [
            {
                "bag_no": bag.bag_no,
                "spoo_last4": bag.spoo_code[-4:],
                "spoo_masked": masked_spoo(bag.spoo_code),
                "spoo_code": bag.spoo_code,
                "closed_at": bag.closed_at.isoformat(),
            }
            for bag in bags
        ],
    }


def search_orders(
    db: Session,
    *,
    q: str | None = None,
    order_id: str | None = None,
    spoo: str | None = None,
    username: str | None = None,
    from_at: datetime | None = None,
    to_at: datetime | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    matching_ids: set[str] | None = None

    def intersect(ids: Iterable[str]) -> None:
        nonlocal matching_ids
        value = set(ids)
        matching_ids = value if matching_ids is None else matching_ids & value

    if order_id:
        rows = db.scalars(
            select(Order.id).where(or_(Order.id == order_id, Order.external_ref == order_id))
        ).all()
        intersect(rows)

    if spoo:
        needle = spoo.strip().upper()
        rows = db.scalars(
            select(OrderBag.order_id).where(
                or_(OrderBag.spoo_code == needle, OrderBag.spoo_code.like(f"%{needle}"))
            )
        ).all()
        intersect(rows)

    if username:
        users = db.scalars(select(User.id).where(func.lower(User.username) == username.strip().lower())).all()
        rows = db.scalars(select(PickTask.order_id).where(PickTask.assigned_user_id.in_(users or ["__none__"]))).all()
        intersect(rows)

    if q:
        needle = q.strip()
        q_ids = set(db.scalars(
            select(Order.id).where(
                or_(
                    Order.id.ilike(f"%{needle}%"),
                    Order.external_ref.ilike(f"%{needle}%"),
                )
            )
        ).all())
        q_ids.update(db.scalars(
            select(OrderBag.order_id).where(OrderBag.spoo_code.ilike(f"%{needle}%"))
        ).all())
        user_ids = db.scalars(select(User.id).where(User.username.ilike(f"%{needle}%"))).all()
        if user_ids:
            q_ids.update(db.scalars(select(PickTask.order_id).where(PickTask.assigned_user_id.in_(user_ids))).all())
        intersect(q_ids)

    query = select(Order, PickTask).outerjoin(PickTask, PickTask.order_id == Order.id)
    if matching_ids is not None:
        if not matching_ids:
            return []
        query = query.where(Order.id.in_(matching_ids))
    if from_at:
        query = query.where(func.coalesce(PickTask.finished_at, Order.updated_at) >= from_at)
    if to_at:
        query = query.where(func.coalesce(PickTask.finished_at, Order.updated_at) <= to_at)

    pairs = db.execute(
        query.order_by(func.coalesce(PickTask.finished_at, Order.updated_at).desc()).limit(max(1, min(limit, 500)))
    ).all()

    results = []
    for order, task in pairs:
        summary = order_completion_summary(db, order.id)
        summary["task_id"] = task.id if task else None
        results.append(summary)
    return results


def _hold_is_effective(hold: FulfillmentHold, at: datetime | None = None) -> bool:
    at = at or now_utc()
    if not hold.active:
        return False
    starts = _utc(hold.starts_at)
    expires = _utc(hold.expires_at)
    return bool((starts is None or starts <= at) and (expires is None or expires > at))


def _hold_matches(hold: FulfillmentHold, product: Product, location: Location) -> bool:
    if hold.site_id and location.site_id != hold.site_id:
        return False
    scope = hold.scope_type.upper()
    value = hold.scope_value.strip().upper()
    if scope == "SITE":
        return value in {"*", location.site_id.upper()}
    if scope == "DOMAIN":
        return domain_for_location(location).upper() == value
    if scope == "ZONE":
        return value in {
            (location.classification or "").upper(),
            (location.fixture_type or "").upper(),
            domain_for_location(location).upper(),
        }
    if scope == "AISLE":
        return str(location.aisle or "").upper() == value.replace("AISLE-", "")
    if scope == "BIN":
        return location.id.upper() == value
    if scope == "SKU":
        return value in {product.id.upper(), product.asin.upper()}
    return False


def location_holds(
    db: Session,
    product: Product,
    location: Location,
    *,
    hard_only: bool = False,
) -> list[FulfillmentHold]:
    holds = db.scalars(
        select(FulfillmentHold).where(
            FulfillmentHold.active == True,  # noqa: E712
            FulfillmentHold.site_id == location.site_id,
        )
    ).all()
    return [
        hold
        for hold in holds
        if _hold_is_effective(hold)
        and (not hard_only or hold.hard_stop)
        and _hold_matches(hold, product, location)
    ]


def is_location_fulfillable(db: Session, product: Product, location: Location) -> bool:
    return not location_holds(db, product, location)


def hard_stop_for_location(db: Session, product: Product, location: Location) -> FulfillmentHold | None:
    blockers = location_holds(db, product, location, hard_only=True)
    return blockers[0] if blockers else None


def product_orderability(db: Session, product_id: str) -> dict[str, Any]:
    product = db.get(Product, product_id)
    if not product:
        raise OpsError("Product not found", "PRODUCT_NOT_FOUND")
    balances = db.scalars(select(InventoryBalance).where(InventoryBalance.product_id == product_id)).all()

    physical = 0
    fulfillable = 0
    blocked = 0
    reasons: set[str] = set()
    for bal in balances:
        location = db.get(Location, bal.location_id)
        if not location or not location.active or not location.pickable or not location.sellable:
            continue
        available = max(0, bal.qty_on_hand - bal.qty_reserved)
        physical += available
        blockers = location_holds(db, product, location)
        if blockers:
            blocked += available
            reasons.update(f"{h.scope_type}:{h.scope_value}:{h.reason}" for h in blockers)
        else:
            fulfillable += available

    return {
        "product_id": product.id,
        "asin": product.asin,
        "physical_stock": physical,
        "fulfillable_stock": fulfillable,
        "blocked_stock": blocked,
        "orderable": fulfillable > 0,
        "blocked_reasons": sorted(reasons),
    }


def create_hold(
    db: Session,
    *,
    site_id: str,
    scope_type: str,
    scope_value: str,
    reason: str,
    created_by_user_id: str,
    notes: str | None = None,
    hard_stop: bool = False,
    starts_at: datetime | None = None,
    expires_at: datetime | None = None,
) -> FulfillmentHold:
    scope = scope_type.strip().upper()
    if scope not in VALID_HOLD_SCOPES:
        raise OpsError(f"Unsupported hold scope {scope}", "BAD_HOLD_SCOPE")
    if expires_at and starts_at and _utc(expires_at) <= _utc(starts_at):
        raise OpsError("expires_at must be after starts_at", "BAD_HOLD_WINDOW")
    hold = FulfillmentHold(
        site_id=site_id.strip().upper(),
        scope_type=scope,
        scope_value=scope_value.strip().upper(),
        reason=reason.strip().upper(),
        notes=notes,
        hard_stop=hard_stop,
        starts_at=starts_at or now_utc(),
        expires_at=expires_at,
        created_by_user_id=created_by_user_id,
    )
    db.add(hold)
    db.flush()
    db.add(OperationalIncident(
        incident_type="FULFILLMENT_HOLD",
        severity="CRITICAL" if hard_stop else "MEDIUM",
        site_id=hold.site_id,
        scope_type=hold.scope_type,
        scope_value=hold.scope_value,
        source_ref=hold.id,
        details_json=json.dumps(
            {"reason": hold.reason, "hard_stop": hold.hard_stop},
            separators=(",", ":"),
        ),
        created_by_user_id=created_by_user_id,
    ))
    db.flush()
    return hold


def resume_hold(db: Session, hold: FulfillmentHold, user_id: str) -> FulfillmentHold:
    hold.active = False
    hold.ended_at = now_utc()
    hold.ended_by_user_id = user_id
    db.flush()
    return hold


def hold_impact(db: Session, hold: FulfillmentHold) -> dict[str, Any]:
    balances = db.scalars(select(InventoryBalance).where(InventoryBalance.qty_on_hand > 0)).all()
    impacted_products: set[str] = set()
    impacted_locations: set[str] = set()
    affected_units = 0
    for bal in balances:
        product = db.get(Product, bal.product_id)
        location = db.get(Location, bal.location_id)
        if not product or not location or not _hold_matches(hold, product, location):
            continue
        impacted_products.add(product.id)
        impacted_locations.add(location.id)
        affected_units += max(0, bal.qty_on_hand - bal.qty_reserved)

    fully_unavailable = 0
    still_available_elsewhere = 0
    for product_id in impacted_products:
        availability = product_orderability(db, product_id)
        if availability["fulfillable_stock"] <= 0:
            fully_unavailable += 1
        else:
            still_available_elsewhere += 1

    return {
        "hold_id": hold.id,
        "scope_type": hold.scope_type,
        "scope_value": hold.scope_value,
        "affected_skus": len(impacted_products),
        "affected_locations": len(impacted_locations),
        "affected_available_units": affected_units,
        "fully_unavailable_skus": fully_unavailable,
        "still_available_elsewhere": still_available_elsewhere,
    }


def list_effective_holds(db: Session, site_id: str = "DEMO") -> list[dict[str, Any]]:
    rows = db.scalars(
        select(FulfillmentHold)
        .where(FulfillmentHold.site_id == site_id.upper())
        .order_by(FulfillmentHold.created_at.desc())
    ).all()
    return [
        {
            "id": h.id,
            "scope_type": h.scope_type,
            "scope_value": h.scope_value,
            "reason": h.reason,
            "notes": h.notes,
            "hard_stop": h.hard_stop,
            "effective": _hold_is_effective(h),
            "active": h.active,
            "starts_at": h.starts_at.isoformat(),
            "expires_at": h.expires_at.isoformat() if h.expires_at else None,
        }
        for h in rows
    ]


def _record_pick_exception(
    db: Session,
    *,
    event_id: str,
    task: PickTask,
    item: PickTaskItem,
    user_id: str,
    exception_type: str,
    reason: str,
    qty: int,
) -> PickException:
    existing = db.scalar(select(PickException).where(PickException.event_id == event_id))
    if existing:
        return existing
    row = PickException(
        event_id=event_id,
        task_id=task.id,
        task_item_id=item.id,
        order_id=task.order_id,
        user_id=user_id,
        location_id=item.source_location_id,
        product_id=item.product_id,
        exception_type=exception_type,
        reason=reason.strip().upper(),
        qty=qty,
    )
    db.add(row)
    db.flush()
    return row


def shortage_side_effects(
    db: Session,
    *,
    event_id: str,
    task: PickTask,
    item: PickTaskItem,
    user_id: str,
    exception_type: str,
    reason: str,
    qty: int,
) -> dict[str, Any]:
    row = _record_pick_exception(
        db,
        event_id=event_id,
        task=task,
        item=item,
        user_id=user_id,
        exception_type=exception_type,
        reason=reason,
        qty=qty,
    )

    cutoff = now_utc() - timedelta(minutes=30)
    recent_count = db.scalar(
        select(func.count())
        .select_from(PickException)
        .where(
            PickException.product_id == item.product_id,
            PickException.location_id == item.source_location_id,
            PickException.exception_type.in_(["SHORT", "DAMAGED"]),
            PickException.created_at >= cutoff,
        )
    ) or 0

    alert = None
    if recent_count >= 3:
        alert = db.scalar(
            select(InventoryAlert).where(
                InventoryAlert.alert_type == "REPEATED_SHORT",
                InventoryAlert.product_id == item.product_id,
                InventoryAlert.location_id == item.source_location_id,
                InventoryAlert.status == "OPEN",
            )
        )
        if alert is None:
            alert = InventoryAlert(
                alert_type="REPEATED_SHORT",
                product_id=item.product_id,
                location_id=item.source_location_id,
                severity="HIGH",
                source_ref=row.id,
                details_json=json.dumps(
                    {
                        "recent_30m": int(recent_count),
                        "suggested_action": "CYCLE_COUNT",
                    },
                    separators=(",", ":"),
                ),
            )
            db.add(alert)
            db.flush()
            incident = OperationalIncident(
                incident_type="REPEATED_SHORTAGE",
                severity="HIGH",
                site_id=(db.get(Location, item.source_location_id).site_id if db.get(Location, item.source_location_id) else "DEMO"),
                scope_type="BIN",
                scope_value=item.source_location_id,
                source_ref=alert.id,
                details_json=json.dumps(
                    {
                        "product_id": item.product_id,
                        "recent_30m": int(recent_count),
                        "suggested_action": "CYCLE_COUNT",
                    },
                    separators=(",", ":"),
                ),
            )
            db.add(incident)
            db.flush()
            enqueue_outbox(
                db,
                topic="incident.created",
                aggregate_type="OPERATIONAL_INCIDENT",
                aggregate_id=incident.id,
                payload={
                    "incident_type": incident.incident_type,
                    "severity": incident.severity,
                    "site_id": incident.site_id,
                    "scope_type": incident.scope_type,
                    "scope_value": incident.scope_value,
                    "source_ref": incident.source_ref,
                    "details": json.loads(incident.details_json),
                },
            )

    existing_replenishment = db.scalar(
        select(ReplenishmentTask).where(
            ReplenishmentTask.product_id == item.product_id,
            ReplenishmentTask.destination_location_id == item.source_location_id,
            ReplenishmentTask.status.in_(["READY", "ASSIGNED"]),
        )
    )
    replenishment = existing_replenishment
    if replenishment is None:
        alternatives = db.scalars(
            select(InventoryBalance).where(
                InventoryBalance.product_id == item.product_id,
                InventoryBalance.location_id != item.source_location_id,
                (InventoryBalance.qty_on_hand - InventoryBalance.qty_reserved) > 0,
            )
        ).all()
        candidates = []
        product = db.get(Product, item.product_id)
        for bal in alternatives:
            loc = db.get(Location, bal.location_id)
            if not loc or not loc.active or product is None:
                continue
            destination = db.get(Location, item.source_location_id)
            if destination is None or not storage_compatible(product, destination)[0]:
                continue
            candidates.append((0 if not loc.pickable else 1, route_sort_key(loc), bal, loc))
        candidates.sort(key=lambda row: (row[0], row[1]))
        if candidates:
            _, _, bal, loc = candidates[0]
            available = max(0, bal.qty_on_hand - bal.qty_reserved)
            replenishment = ReplenishmentTask(
                product_id=item.product_id,
                source_location_id=loc.id,
                destination_location_id=item.source_location_id,
                qty=min(max(1, qty), available),
                trigger=exception_type,
                source_ref=row.id,
            )
            db.add(replenishment)

    db.flush()
    return {
        "pick_exception_id": row.id,
        "recent_short_count_30m": int(recent_count),
        "cycle_count_alert_id": alert.id if alert else None,
        "replenishment_task_id": replenishment.id if replenishment else None,
    }


def skip_task_item(
    db: Session,
    *,
    task: PickTask,
    item: PickTaskItem,
    event_id: str,
    client_seq: int,
    user_id: str,
    device_id: str,
    reason: str,
) -> dict[str, Any]:
    existing = db.get(ScanEvent, event_id)
    if existing:
        return {"duplicate": True}
    if task.assigned_user_id != user_id or task.assigned_device_id != device_id:
        raise OpsError("Picker/device does not own this order", "OWNERSHIP_MISMATCH")
    if task.status not in {TaskStatus.ACCEPTED.value, TaskStatus.PICKING.value}:
        raise OpsError("Order is not pickable", "INVALID_TASK_STATE")
    if item.task_id != task.id:
        raise OpsError("Task item mismatch", "ITEM_MISMATCH")
    if client_seq != task.client_high_water_seq + 1:
        raise OpsError("Client sequence conflict", "SEQUENCE_CONFLICT")

    max_sequence = db.scalar(select(func.max(PickTaskItem.sequence)).where(PickTaskItem.task_id == task.id)) or item.sequence
    item.sequence = int(max_sequence) + 1
    task.client_high_water_seq = client_seq
    task.server_version += 1
    task.status = TaskStatus.PICKING.value
    task.started_at = task.started_at or now_utc()
    db.add(ScanEvent(
        id=event_id,
        task_id=task.id,
        client_seq=client_seq,
        device_id=device_id,
        user_id=user_id,
        event_type="SKIP",
        status="ACKED",
        payload_json=json.dumps({"task_item_id": item.id, "reason": reason}, separators=(",", ":")),
        server_version_after=task.server_version,
    ))
    _record_pick_exception(
        db,
        event_id=event_id,
        task=task,
        item=item,
        user_id=user_id,
        exception_type="SKIP",
        reason=reason,
        qty=max(0, item.planned_qty - item.picked_qty),
    )
    db.flush()
    return {"duplicate": False}


def damage_task_item(
    db: Session,
    *,
    task: PickTask,
    item: PickTaskItem,
    event_id: str,
    client_seq: int,
    user_id: str,
    device_id: str,
    qty: int,
    reason: str,
) -> dict[str, Any]:
    existing = db.get(ScanEvent, event_id)
    if existing:
        return {"duplicate": True}
    if task.assigned_user_id != user_id or task.assigned_device_id != device_id:
        raise OpsError("Picker/device does not own this order", "OWNERSHIP_MISMATCH")
    if task.status not in {TaskStatus.ACCEPTED.value, TaskStatus.PICKING.value}:
        raise OpsError("Order is not pickable", "INVALID_TASK_STATE")
    if item.task_id != task.id:
        raise OpsError("Task item mismatch", "ITEM_MISMATCH")
    if client_seq != task.client_high_water_seq + 1:
        raise OpsError("Client sequence conflict", "SEQUENCE_CONFLICT")
    remaining = item.planned_qty - item.picked_qty
    if qty <= 0 or qty > remaining:
        raise OpsError(f"Invalid damaged quantity; remaining={remaining}", "QTY_EXCEEDS_PLAN")

    try:
        move_inventory(
            db,
            event_id=f"damage-pick:{event_id}",
            product_id=item.product_id,
            qty=qty,
            source_location_id=item.source_location_id,
            destination_location_id="DMG",
            reason=f"PICK_DAMAGE:{reason[:48]}",
            order_id=task.order_id,
            task_id=task.id,
            user_id=user_id,
            device_id=device_id,
            consume_reserved=True,
        )
    except InventoryError as exc:
        raise OpsError(str(exc), "INVENTORY_CONFLICT") from exc

    item.planned_qty -= qty
    line = db.get(OrderLine, item.order_line_id)
    if line:
        line.shorted_qty += qty
    task.client_high_water_seq = client_seq
    task.server_version += 1
    task.status = TaskStatus.PICKING.value
    task.started_at = task.started_at or now_utc()
    db.add(ScanEvent(
        id=event_id,
        task_id=task.id,
        client_seq=client_seq,
        device_id=device_id,
        user_id=user_id,
        event_type="DAMAGED",
        status="ACKED",
        payload_json=json.dumps(
            {"task_item_id": item.id, "qty": qty, "reason": reason},
            separators=(",", ":"),
        ),
        server_version_after=task.server_version,
    ))
    effects = shortage_side_effects(
        db,
        event_id=event_id,
        task=task,
        item=item,
        user_id=user_id,
        exception_type="DAMAGED",
        reason=reason,
        qty=qty,
    )
    db.flush()
    return {"duplicate": False, **effects}


def performance_rows(db: Session, from_at: datetime, to_at: datetime) -> list[dict[str, Any]]:
    users = db.scalars(
        select(User).where(User.active == True, User.role.in_(PICKER_ROLES)).order_by(User.username)  # noqa: E712
    ).all()
    rows = []
    for user in users:
        tasks = db.scalars(
            select(PickTask).where(
                PickTask.assigned_user_id == user.id,
                PickTask.finished_at.is_not(None),
                PickTask.finished_at >= from_at,
                PickTask.finished_at <= to_at,
            )
        ).all()
        task_ids = [task.id for task in tasks]
        units = 0
        if task_ids:
            units = db.scalar(
                select(func.coalesce(func.sum(PickTaskItem.picked_qty), 0)).where(PickTaskItem.task_id.in_(task_ids))
            ) or 0
        bags = db.scalar(
            select(func.count()).select_from(OrderBag).where(
                OrderBag.closed_by_user_id == user.id,
                OrderBag.closed_at >= from_at,
                OrderBag.closed_at <= to_at,
            )
        ) or 0
        late_slam = db.scalar(
            select(func.count()).select_from(PerformanceEvent).where(
                PerformanceEvent.user_id == user.id,
                PerformanceEvent.event_type == "LATE_SLAM",
                PerformanceEvent.occurred_at >= from_at,
                PerformanceEvent.occurred_at <= to_at,
            )
        ) or 0
        durations = [
            max(0, int((_utc(task.finished_at) - _utc(task.started_at)).total_seconds()))
            for task in tasks
            if task.started_at and task.finished_at
        ]
        profile = db.get(EmployeeProfile, user.id)
        rows.append({
            "user_id": user.id,
            "username": user.username,
            "full_name": profile.full_name if profile else user.username,
            "orders": len(tasks),
            "items": int(units),
            "bags": int(bags),
            "late_slam": int(late_slam),
            "late_slam_rate": round((int(late_slam) / len(tasks)) * 100, 2) if tasks else 0.0,
            "avg_pick_seconds": round(sum(durations) / len(durations), 1) if durations else None,
        })
    return rows


def slotting_suggestions(db: Session, *, days: int = 30, limit: int = 20) -> list[dict[str, Any]]:
    cutoff = now_utc() - timedelta(days=max(1, min(days, 365)))
    rows = db.execute(
        select(PickTaskItem.product_id, func.sum(PickTaskItem.picked_qty).label("units"))
        .join(PickTask, PickTask.id == PickTaskItem.task_id)
        .where(PickTask.finished_at >= cutoff, PickTaskItem.picked_qty > 0)
        .group_by(PickTaskItem.product_id)
        .order_by(func.sum(PickTaskItem.picked_qty).desc())
        .limit(max(1, min(limit, 100)))
    ).all()
    suggestions = []
    for product_id, units in rows:
        product = db.get(Product, product_id)
        balances = db.scalars(
            select(InventoryBalance).where(InventoryBalance.product_id == product_id, InventoryBalance.qty_on_hand > 0)
        ).all()
        locations = [db.get(Location, b.location_id) for b in balances]
        locations = [loc for loc in locations if loc and loc.pickable and loc.sellable]
        aisles = [loc.aisle for loc in locations if loc.aisle is not None]
        suggestions.append({
            "product_id": product_id,
            "asin": product.asin if product else None,
            "title": product.title if product else "Unknown product",
            "picked_units": int(units or 0),
            "current_locations": [loc.id for loc in locations],
            "current_aisles": sorted(set(aisles)),
            "suggestion": "REVIEW_FAST_MOVER_SLOT" if int(units or 0) > 0 else "NONE",
            "action_requires_manager_approval": True,
        })
    return suggestions


def grant_qualification(db: Session, user_id: str, qualification: str, manager_id: str) -> WorkerQualification:
    value = qualification.strip().upper()
    if value not in {"HAZ", "HRV"}:
        raise OpsError("Unsupported qualification", "BAD_QUALIFICATION")
    row = db.scalar(
        select(WorkerQualification).where(
            WorkerQualification.user_id == user_id,
            WorkerQualification.qualification == value,
        )
    )
    if row:
        row.active = True
        row.granted_by_user_id = manager_id
    else:
        row = WorkerQualification(
            user_id=user_id,
            qualification=value,
            active=True,
            granted_by_user_id=manager_id,
        )
        db.add(row)
    db.flush()
    return row


def clock_in_shift(
    db: Session,
    *,
    user_id: str,
    scheduled_start_at: datetime,
    scheduled_end_at: datetime,
    clock_in_at: datetime | None = None,
) -> ShiftSession:
    if scheduled_end_at <= scheduled_start_at:
        raise OpsError("Shift end must be after shift start", "BAD_SHIFT_WINDOW")
    open_shift = db.scalar(
        select(ShiftSession).where(ShiftSession.user_id == user_id, ShiftSession.status == "OPEN")
    )
    if open_shift:
        return open_shift
    profile = db.get(EmployeeProfile, user_id)
    grace_minutes = profile.grace_minutes if profile else 0
    clocked = clock_in_at or now_utc()
    late = max(
        0,
        int((_utc(clocked) - _utc(scheduled_start_at) - timedelta(minutes=grace_minutes)).total_seconds() // 60),
    )
    shift = ShiftSession(
        user_id=user_id,
        scheduled_start_at=scheduled_start_at,
        scheduled_end_at=scheduled_end_at,
        clock_in_at=clocked,
        late_minutes=late,
    )
    db.add(shift)
    set_worker_state(db, user_id, "AVAILABLE", reason="SHIFT_CLOCK_IN", force=True)
    evaluate_guard_rules(db, site_id="DEMO")
    db.flush()
    return shift


def clock_out_shift(db: Session, *, user_id: str, clock_out_at: datetime | None = None) -> ShiftSession:
    shift = db.scalar(
        select(ShiftSession)
        .where(ShiftSession.user_id == user_id, ShiftSession.status == "OPEN")
        .order_by(ShiftSession.created_at.desc())
    )
    if not shift:
        raise OpsError("No open shift", "NO_OPEN_SHIFT")
    if db.get(ActivePickLease, user_id):
        raise OpsError("Cannot clock out with an active order", "ACTIVE_PICK_EXISTS")
    state = get_worker_state(db, user_id, create=True)
    if state and state.state not in {"AVAILABLE", "ENDING_SHIFT"}:
        raise OpsError(f"Cannot clock out while {state.state}", "ACTIVE_OPERATIONAL_TASK")

    out = clock_out_at or now_utc()
    if _utc(out) < _utc(shift.clock_in_at):
        raise OpsError("Clock out cannot be before clock in", "BAD_CLOCK_OUT")
    shift.clock_out_at = out
    shift.status = "CLOSED"
    shift.worked_minutes = max(0, int((_utc(out) - _utc(shift.clock_in_at)).total_seconds() // 60))
    shift.early_leave_minutes = max(0, int((_utc(shift.scheduled_end_at) - _utc(out)).total_seconds() // 60))
    shift.overtime_minutes = max(0, int((_utc(out) - _utc(shift.scheduled_end_at)).total_seconds() // 60))

    attendance = AttendanceEntry(
        user_id=user_id,
        scheduled_start_at=shift.scheduled_start_at,
        clock_in_at=shift.clock_in_at,
        clock_out_at=out,
        late_minutes=shift.late_minutes,
        overtime_minutes=shift.overtime_minutes,
        status="APPROVED",
        source="SYSTEM_CLOCK",
        notes=f"Auto-calculated from shift {shift.id}",
    )
    db.add(attendance)
    db.flush()
    shift.attendance_entry_id = attendance.id
    db.add(AttendanceComputation(
        attendance_entry_id=attendance.id,
        scheduled_end_at=shift.scheduled_end_at,
        early_leave_minutes=shift.early_leave_minutes,
        worked_minutes=shift.worked_minutes,
    ))
    set_worker_state(db, user_id, "OFFLINE", reason="SHIFT_CLOCK_OUT", force=True)
    evaluate_guard_rules(db, site_id="DEMO")
    db.flush()
    return shift


def update_device_telemetry(
    db: Session,
    device_id: str,
    *,
    battery_percent: int | None,
    connectivity: str | None,
    last_location_id: str | None,
    activity: str | None = None,
) -> DeviceTelemetry:
    row = db.get(DeviceTelemetry, device_id)
    if row is None:
        row = DeviceTelemetry(device_id=device_id)
        db.add(row)
    if battery_percent is not None:
        row.battery_percent = max(0, min(100, battery_percent))
    if connectivity is not None:
        row.connectivity = connectivity.strip().upper()
    if last_location_id is not None:
        row.last_location_id = last_location_id.strip().upper()
    if activity is not None:
        row.activity = activity.strip().upper()[:80]
    row.updated_at = now_utc()
    db.flush()
    return row


def _shipment_temp_handling(domain: str) -> tuple[str, str]:
    value = domain.upper()
    if value == "CHILLED":
        return "CHILLED", "STANDARD"
    if value == "FROZEN":
        return "FROZEN", "STANDARD"
    if value == "HAZ":
        return "AMBIENT", "HAZ"
    if value == "HRV":
        return "AMBIENT", "HRV"
    return "AMBIENT", "STANDARD"


def create_shipment(
    db: Session,
    *,
    label: str,
    shipment_type: str,
    storage_domain: str,
    lines: list[dict[str, Any]],
    created_by_user_id: str,
    target_stow_minutes: int | None = None,
) -> Shipment:
    domain = storage_domain.strip().upper()
    if domain not in SHIPMENT_DOMAINS:
        raise OpsError("Unsupported storage domain", "BAD_STORAGE_DOMAIN")
    if db.scalar(select(Shipment).where(Shipment.label == label.strip().upper())):
        raise OpsError("Shipment label already exists", "SHIPMENT_EXISTS")

    default_target = 30 if domain in {"CHILLED", "FROZEN"} else 120
    shipment = Shipment(
        label=label.strip().upper(),
        shipment_type=shipment_type.strip().upper(),
        storage_domain=domain,
        target_stow_minutes=target_stow_minutes or default_target,
        created_by_user_id=created_by_user_id,
    )
    db.add(shipment)
    db.flush()

    expected_total = 0
    for spec in lines:
        product_id = str(spec["product_id"])
        expected = max(0, int(spec.get("expected_qty", 0)))
        if db.get(Product, product_id) is None:
            raise OpsError(f"Unknown product {product_id}", "PRODUCT_NOT_FOUND")
        db.add(ShipmentLine(
            shipment_id=shipment.id,
            product_id=product_id,
            expected_qty=expected,
            lot_code=spec.get("lot_code"),
            expires_on=spec.get("expires_on"),
        ))
        expected_total += expected
    shipment.expected_units = expected_total
    db.flush()
    return shipment


def dock_check_in(db: Session, shipment: Shipment, dock_ref: str) -> Shipment:
    if shipment.status not in {"CREATED", "DOCKED"}:
        raise OpsError(f"Shipment cannot dock from {shipment.status}", "INVALID_SHIPMENT_STATE")
    shipment.dock_ref = dock_ref.strip().upper()
    shipment.status = "DOCKED"
    db.flush()
    return shipment


def open_shipment_receiving(
    db: Session,
    *,
    shipment: Shipment,
    user_id: str,
    device_id: str,
) -> ReceivingSession:
    if shipment.status not in {"CREATED", "DOCKED", "RECEIVING"}:
        raise OpsError(f"Shipment cannot be opened from {shipment.status}", "INVALID_SHIPMENT_STATE")
    if db.get(ActivePickLease, user_id):
        raise OpsError("Worker has an active pick order", "ACTIVE_PICK_EXISTS")
    user = db.get(User, user_id)
    if not user:
        raise OpsError("Worker not found", "WORKER_NOT_FOUND")

    existing = db.scalar(
        select(ReceivingSession).where(
            ReceivingSession.shipment_id == shipment.id,
            ReceivingSession.user_id == user_id,
            ReceivingSession.status == "OPEN",
        )
    )
    if existing:
        return existing

    temp, handling = _shipment_temp_handling(shipment.storage_domain)
    if shipment.storage_domain in {"HAZ", "HRV"} and shipment.storage_domain not in worker_qualifications(db, user_id):
        raise OpsError(f"{shipment.storage_domain} qualification required", "QUALIFICATION_REQUIRED")

    inbound_id = shipment.inbound_location_id or f"INBOUND:{shipment.id}"
    if db.get(Location, inbound_id) is None:
        db.add(Location(
            id=inbound_id,
            site_id="DEMO",
            classification="INBOUND",
            temperature_class=temp,
            handling_class=handling,
            pickable=False,
            stowable=True,
            logical=True,
            sellable=False,
            active=True,
        ))
        db.flush()
    shipment.inbound_location_id = inbound_id
    shipment.status = "RECEIVING"
    shipment.opened_at = shipment.opened_at or now_utc()

    session = ReceivingSession(
        shipment_id=shipment.id,
        user_id=user_id,
        device_id=device_id,
    )
    db.add(session)
    set_worker_state(
        db,
        user_id,
        f"RECEIVING_{shipment.storage_domain}",
        activity_ref=shipment.id,
        reason="SHIPMENT_RECEIVING",
    )
    db.flush()
    return session


def receive_shipment_line(
    db: Session,
    *,
    shipment: Shipment,
    session: ReceivingSession,
    event_id: str,
    product_id: str,
    good_qty: int,
    damaged_qty: int = 0,
    lot_code: str | None = None,
    expires_on: date | None = None,
) -> dict[str, Any]:
    if session.status != "OPEN" or shipment.status != "RECEIVING":
        raise OpsError("Receiving session is not open", "SESSION_CLOSED")
    if good_qty < 0 or damaged_qty < 0 or good_qty + damaged_qty <= 0:
        raise OpsError("Received quantity must be positive", "BAD_QUANTITY")
    line = db.scalar(
        select(ShipmentLine).where(ShipmentLine.shipment_id == shipment.id, ShipmentLine.product_id == product_id)
    )
    if line is None:
        line = ShipmentLine(shipment_id=shipment.id, product_id=product_id, expected_qty=0)
        db.add(line)
        db.flush()
    product = db.get(Product, product_id)
    if not product:
        raise OpsError("Unknown product", "PRODUCT_NOT_FOUND")

    if shipment.storage_domain == "CHILLED" and product.temperature_class != "CHILLED":
        raise OpsError("Product is not chilled", "TEMPERATURE_MISMATCH")
    if shipment.storage_domain == "FROZEN" and product.temperature_class != "FROZEN":
        raise OpsError("Product is not frozen", "TEMPERATURE_MISMATCH")
    if shipment.storage_domain == "HAZ" and product.handling_class != "HAZ":
        raise OpsError("Product is not HAZ", "CLASSIFICATION_MISMATCH")
    if shipment.storage_domain == "HRV" and product.handling_class != "HRV":
        raise OpsError("Product is not HRV", "CLASSIFICATION_MISMATCH")

    inbound = shipment.inbound_location_id
    if not inbound:
        raise OpsError("Shipment has no inbound location", "INBOUND_NOT_READY")

    try:
        good_move = None
        if good_qty:
            good_move = move_inventory(
                db,
                event_id=f"shipment-good:{event_id}",
                product_id=product_id,
                qty=good_qty,
                source_location_id=None,
                destination_location_id=inbound,
                reason="SHIPMENT_RECEIVE",
                user_id=session.user_id,
                device_id=session.device_id,
            )
        damage_move = None
        if damaged_qty:
            damage_move = move_inventory(
                db,
                event_id=f"shipment-dmg:{event_id}",
                product_id=product_id,
                qty=damaged_qty,
                source_location_id=None,
                destination_location_id="DMG",
                reason="SHIPMENT_DAMAGE",
                user_id=session.user_id,
                device_id=session.device_id,
            )
    except InventoryError as exc:
        raise OpsError(str(exc), "INVENTORY_CONFLICT") from exc

    # Inventory movement IDs make receive retries safe. Only aggregate on first commit.
    duplicate = bool(
        (good_qty == 0 or (good_move and good_move.duplicate))
        and (damaged_qty == 0 or (damage_move and damage_move.duplicate))
    )
    if not duplicate:
        line.received_qty += good_qty
        line.damaged_qty += damaged_qty
        if lot_code:
            line.lot_code = lot_code.strip().upper()
        if expires_on:
            line.expires_on = expires_on
        shipment.received_units += good_qty
        shipment.damaged_units += damaged_qty

        if good_qty and (lot_code or expires_on):
            normalized_lot = (lot_code or f"AUTO-{event_id[:16]}").strip().upper()
            lot = db.scalar(
                select(InventoryLot).where(
                    InventoryLot.product_id == product_id,
                    InventoryLot.location_id == inbound,
                    InventoryLot.lot_code == normalized_lot,
                )
            )
            if lot is None:
                lot = InventoryLot(
                    product_id=product_id,
                    location_id=inbound,
                    lot_code=normalized_lot,
                    expires_on=expires_on,
                    qty=0,
                )
                db.add(lot)
            lot.qty += good_qty
            if expires_on:
                lot.expires_on = expires_on
    db.flush()
    return {
        "duplicate": duplicate,
        "shipment_id": shipment.id,
        "line_id": line.id,
        "received_good": line.received_qty,
        "received_damaged": line.damaged_qty,
    }


def recommend_stow_locations(db: Session, shipment: Shipment, product_id: str, limit: int = 10) -> list[dict[str, Any]]:
    product = db.get(Product, product_id)
    if not product:
        return []
    locations = db.scalars(
        select(Location).where(
            Location.logical == False,  # noqa: E712
            Location.active == True,  # noqa: E712
            Location.stowable == True,  # noqa: E712
            Location.sellable == True,  # noqa: E712
        )
    ).all()
    stow_qty = db.scalar(
        select(func.max(StowTask.qty)).where(
            StowTask.shipment_id == shipment.id,
            StowTask.product_id == product_id,
            StowTask.status.in_(["READY", "ASSIGNED"]),
        )
    ) or 1
    compatible = [
        loc for loc in locations
        if storage_compatible(product, loc)[0]
        and destination_has_capacity(db, loc.id, int(stow_qty))
    ]
    scored = []
    for loc in compatible:
        bal = db.scalar(
            select(InventoryBalance).where(
                InventoryBalance.location_id == loc.id,
                InventoryBalance.product_id == product_id,
            )
        )
        current_qty = bal.qty_on_hand if bal else 0
        scored.append((route_sort_key(loc), current_qty, loc))
    scored.sort(key=lambda row: (row[0], row[1]))
    return [
        {
            "location_id": loc.id,
            "current_product_qty": qty,
            "domain": domain_for_location(loc),
        }
        for _, qty, loc in scored[: max(1, min(limit, 50))]
    ]


def complete_receiving(db: Session, shipment: Shipment, session: ReceivingSession) -> dict[str, Any]:
    if session.status != "OPEN":
        return shipment_payload(db, shipment)
    lines = db.scalars(select(ShipmentLine).where(ShipmentLine.shipment_id == shipment.id)).all()
    total_missing = 0
    for line in lines:
        line.missing_qty = max(0, line.expected_qty - line.received_qty - line.damaged_qty)
        total_missing += line.missing_qty
        if line.received_qty > 0:
            existing = db.scalar(
                select(StowTask).where(
                    StowTask.shipment_id == shipment.id,
                    StowTask.product_id == line.product_id,
                    StowTask.status.in_(["READY", "ASSIGNED"]),
                )
            )
            if existing is None:
                db.add(StowTask(
                    shipment_id=shipment.id,
                    product_id=line.product_id,
                    source_location_id=shipment.inbound_location_id,
                    qty=line.received_qty,
                    assigned_user_id=session.user_id,
                ))

    shipment.missing_units = total_missing
    shipment.received_at = now_utc()
    shipment.status = "STOWING"
    session.status = "COMPLETED"
    session.completed_at = now_utc()
    set_worker_state(db, session.user_id, "STOWING", activity_ref=shipment.id, reason="RECEIVE_COMPLETE")
    db.flush()
    return shipment_payload(db, shipment)


def _move_lots_for_stow(
    db: Session,
    *,
    product_id: str,
    source_location_id: str,
    destination_location_id: str,
    qty: int,
) -> None:
    remaining = qty
    lots = db.scalars(
        select(InventoryLot)
        .where(
            InventoryLot.product_id == product_id,
            InventoryLot.location_id == source_location_id,
            InventoryLot.qty > 0,
        )
        .order_by(InventoryLot.expires_on.asc().nullslast(), InventoryLot.lot_code.asc())
    ).all()
    for lot in lots:
        if remaining <= 0:
            break
        moved = min(remaining, lot.qty)
        lot.qty -= moved
        dest = db.scalar(
            select(InventoryLot).where(
                InventoryLot.product_id == product_id,
                InventoryLot.location_id == destination_location_id,
                InventoryLot.lot_code == lot.lot_code,
            )
        )
        if dest is None:
            dest = InventoryLot(
                product_id=product_id,
                location_id=destination_location_id,
                lot_code=lot.lot_code,
                expires_on=lot.expires_on,
                qty=0,
            )
            db.add(dest)
        dest.qty += moved
        remaining -= moved


def complete_stow_task(
    db: Session,
    *,
    task: StowTask,
    destination_location_id: str,
    user_id: str,
    device_id: str,
    event_id: str,
) -> dict[str, Any]:
    if task.status == "COMPLETED":
        return {"task_id": task.id, "status": task.status, "destination_location_id": task.destination_location_id}
    if task.assigned_user_id and task.assigned_user_id != user_id:
        raise OpsError("Stow task belongs to another worker", "OWNERSHIP_MISMATCH")

    product = db.get(Product, task.product_id)
    destination = db.get(Location, destination_location_id)
    if not product or not destination:
        raise OpsError("Unknown product or destination", "NOT_FOUND")
    compatible, code = storage_compatible(product, destination)
    if not compatible:
        raise OpsError(f"Destination is incompatible: {code}", code or "INCOMPATIBLE")

    try:
        move = move_inventory(
            db,
            event_id=f"shipment-stow:{event_id}",
            product_id=task.product_id,
            qty=task.qty,
            source_location_id=task.source_location_id,
            destination_location_id=destination_location_id,
            reason="SHIPMENT_STOW",
            task_id=task.id,
            user_id=user_id,
            device_id=device_id,
        )
    except InventoryError as exc:
        raise OpsError(str(exc), "INVENTORY_CONFLICT") from exc

    if not move.duplicate:
        _move_lots_for_stow(
            db,
            product_id=task.product_id,
            source_location_id=task.source_location_id,
            destination_location_id=destination_location_id,
            qty=task.qty,
        )
        task.destination_location_id = destination_location_id
        task.status = "COMPLETED"
        task.completed_at = now_utc()

    remaining = db.scalar(
        select(func.count()).select_from(StowTask).where(
            StowTask.shipment_id == task.shipment_id,
            StowTask.status != "COMPLETED",
        )
    ) or 0
    shipment = db.get(Shipment, task.shipment_id)
    if remaining == 0 and shipment:
        shipment.status = "COMPLETED"
        shipment.completed_at = now_utc()
        set_worker_state(db, user_id, "AVAILABLE", reason="SHIPMENT_STOW_COMPLETE", force=True)

    db.flush()
    return {
        "task_id": task.id,
        "status": task.status,
        "destination_location_id": task.destination_location_id,
        "shipment_completed": bool(shipment and shipment.status == "COMPLETED"),
    }


def shipment_payload(db: Session, shipment: Shipment) -> dict[str, Any]:
    lines = db.scalars(select(ShipmentLine).where(ShipmentLine.shipment_id == shipment.id)).all()
    stow_tasks = db.scalars(select(StowTask).where(StowTask.shipment_id == shipment.id)).all()
    elapsed_minutes = None
    if shipment.opened_at:
        end = shipment.completed_at or now_utc()
        elapsed_minutes = max(0, int((_utc(end) - _utc(shipment.opened_at)).total_seconds() // 60))
    return {
        "id": shipment.id,
        "label": shipment.label,
        "shipment_type": shipment.shipment_type,
        "storage_domain": shipment.storage_domain,
        "status": shipment.status,
        "dock_ref": shipment.dock_ref,
        "expected_units": shipment.expected_units,
        "received_units": shipment.received_units,
        "damaged_units": shipment.damaged_units,
        "missing_units": shipment.missing_units,
        "target_stow_minutes": shipment.target_stow_minutes,
        "elapsed_minutes": elapsed_minutes,
        "stow_overdue": bool(
            elapsed_minutes is not None
            and shipment.status not in {"COMPLETED", "CANCELLED"}
            and elapsed_minutes > shipment.target_stow_minutes
        ),
        "lines": [
            {
                "id": line.id,
                "product_id": line.product_id,
                "expected_qty": line.expected_qty,
                "received_qty": line.received_qty,
                "damaged_qty": line.damaged_qty,
                "missing_qty": line.missing_qty,
                "lot_code": line.lot_code,
                "expires_on": line.expires_on.isoformat() if line.expires_on else None,
                "recommended_stow": recommend_stow_locations(db, shipment, line.product_id, 5),
            }
            for line in lines
        ],
        "stow_tasks": [
            {
                "id": task.id,
                "product_id": task.product_id,
                "qty": task.qty,
                "status": task.status,
                "destination_location_id": task.destination_location_id,
                "assigned_user_id": task.assigned_user_id,
            }
            for task in stow_tasks
        ],
    }
