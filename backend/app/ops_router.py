from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db
from .models import Device, EmployeeProfile, PickTask, PickTaskItem, User
from .models_ops import (
    DeviceTelemetry,
    FulfillmentHold,
    InventoryAlert,
    ReplenishmentTask,
    Shipment,
    StowTask,
    WorkerQualification,
)
from .security import authenticate_access
from .services.ops_platform import (
    OpsError,
    broadcast_task,
    claim_task,
    clock_in_shift,
    clock_out_shift,
    close_order_bag,
    complete_receiving,
    complete_stow_task,
    create_hold,
    create_shipment,
    direct_assign_task,
    finalize_pick_session,
    get_worker_state,
    grant_qualification,
    hold_impact,
    list_effective_holds,
    my_open_offers,
    open_shipment_receiving,
    order_completion_summary,
    performance_rows,
    product_orderability,
    receive_shipment_line,
    recommend_stow_locations,
    resume_hold,
    search_orders,
    set_worker_state,
    shipment_payload,
    skip_task_item,
    damage_task_item,
    slotting_suggestions,
    update_device_telemetry,
    worker_dispatch_status,
)
from .services.picking import task_snapshot
from .services.workforce import MANAGER_ROLES


router = APIRouter(tags=["operations-v0.3"])


def ops_actor(
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
) -> tuple[User, Device]:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing bearer token")
    auth = authenticate_access(db, authorization[7:])
    if not auth:
        raise HTTPException(401, "Session expired or invalid")
    user, device = auth[0], auth[1]
    db.commit()
    return user, device


def ops_manager(who=Depends(ops_actor)) -> tuple[User, Device]:
    user, device = who
    if user.role.upper() not in MANAGER_ROLES:
        raise HTTPException(403, "Supervisor or admin role required")
    return user, device


def fail(exc: OpsError) -> None:
    raise HTTPException(409, {"code": exc.code, "message": str(exc)})


class WorkerStateRequest(BaseModel):
    state: str
    activity_ref: str | None = None
    reason: str | None = None


class DirectAssignRequest(BaseModel):
    user_id: str
    device_id: str | None = None
    reason: str = "MANUAL_DISPATCH"


class BroadcastRequest(BaseModel):
    ttl_seconds: int = Field(default=90, ge=10, le=600)


class BagCloseRequest(BaseModel):
    spoo_code: str = Field(min_length=4, max_length=120)


class QualificationRequest(BaseModel):
    user_id: str
    qualification: str


class HoldCreateRequest(BaseModel):
    site_id: str = "DEMO"
    scope_type: str
    scope_value: str
    reason: str
    notes: str | None = None
    hard_stop: bool = False
    starts_at: datetime | None = None
    expires_at: datetime | None = None


class PickExceptionRequest(BaseModel):
    event_id: str
    client_seq: int = Field(gt=0)
    task_item_id: str
    reason: str = "NOT_FOUND"
    qty: int = Field(default=1, gt=0)


class ShiftClockInRequest(BaseModel):
    scheduled_start_at: datetime
    scheduled_end_at: datetime
    clock_in_at: datetime | None = None


class ShiftClockOutRequest(BaseModel):
    clock_out_at: datetime | None = None


class DeviceTelemetryRequest(BaseModel):
    battery_percent: int | None = Field(default=None, ge=0, le=100)
    connectivity: str | None = None
    last_location_id: str | None = None


class ShipmentLineInput(BaseModel):
    product_id: str
    expected_qty: int = Field(default=0, ge=0)
    lot_code: str | None = None
    expires_on: date | None = None


class ShipmentCreateRequest(BaseModel):
    label: str
    shipment_type: str = "VENDOR"
    storage_domain: str = "AMBIENT"
    target_stow_minutes: int | None = Field(default=None, ge=5, le=1440)
    lines: list[ShipmentLineInput] = []


class DockCheckInRequest(BaseModel):
    dock_ref: str


class ShipmentReceiveRequest(BaseModel):
    event_id: str
    product_id: str
    good_qty: int = Field(default=0, ge=0)
    damaged_qty: int = Field(default=0, ge=0)
    lot_code: str | None = None
    expires_on: date | None = None


class StowCompleteRequest(BaseModel):
    event_id: str
    destination_location_id: str


@router.get("/ops/me/state")
def my_state(who=Depends(ops_actor), db: Session = Depends(get_db)):
    user, _ = who
    state = get_worker_state(db, user.id, create=True)
    return {
        "user_id": user.id,
        "username": user.username,
        "state": state.state,
        "activity_ref": state.activity_ref,
        "reason": state.reason,
        "updated_at": state.updated_at.isoformat(),
    }


@router.post("/ops/me/state")
def change_my_state(req: WorkerStateRequest, who=Depends(ops_actor), db: Session = Depends(get_db)):
    user, _ = who
    allowed = {
        "AVAILABLE", "BREAK", "BOH_MOVE", "UNPACKING", "CYCLE_COUNT",
        "EXPIRY_AUDIT", "BIN_CHECK", "VENDOR_REMOVAL", "TRAINING", "ENDING_SHIFT",
    }
    if req.state.strip().upper() not in allowed:
        raise HTTPException(400, "Unsupported self-service state")
    try:
        with db.begin():
            state = set_worker_state(
                db,
                user.id,
                req.state,
                activity_ref=req.activity_ref,
                reason=req.reason,
            )
            return {
                "state": state.state,
                "activity_ref": state.activity_ref,
                "dispatch_blocked": state.state != "AVAILABLE",
            }
    except OpsError as exc:
        fail(exc)


@router.post("/ops/shifts/clock-in")
def shift_clock_in(req: ShiftClockInRequest, who=Depends(ops_actor), db: Session = Depends(get_db)):
    user, _ = who
    try:
        with db.begin():
            shift = clock_in_shift(
                db,
                user_id=user.id,
                scheduled_start_at=req.scheduled_start_at,
                scheduled_end_at=req.scheduled_end_at,
                clock_in_at=req.clock_in_at,
            )
            return {
                "shift_id": shift.id,
                "status": shift.status,
                "late_minutes": shift.late_minutes,
                "clock_in_at": shift.clock_in_at.isoformat(),
            }
    except OpsError as exc:
        fail(exc)


@router.post("/ops/shifts/clock-out")
def shift_clock_out(req: ShiftClockOutRequest, who=Depends(ops_actor), db: Session = Depends(get_db)):
    user, _ = who
    try:
        with db.begin():
            shift = clock_out_shift(db, user_id=user.id, clock_out_at=req.clock_out_at)
            return {
                "shift_id": shift.id,
                "status": shift.status,
                "worked_minutes": shift.worked_minutes,
                "late_minutes": shift.late_minutes,
                "early_leave_minutes": shift.early_leave_minutes,
                "overtime_minutes": shift.overtime_minutes,
                "clock_out_at": shift.clock_out_at.isoformat() if shift.clock_out_at else None,
            }
    except OpsError as exc:
        fail(exc)


@router.get("/ops/dispatch/workers")
def dispatch_workers(
    task_id: str | None = None,
    who=Depends(ops_manager),
    db: Session = Depends(get_db),
):
    task = db.get(PickTask, task_id) if task_id else None
    users = db.scalars(select(User).where(User.active == True).order_by(User.username)).all()  # noqa: E712
    rows = []
    for user in users:
        if user.role.upper() not in {"PICKER", "SENIOR_PICKER"}:
            continue
        row = worker_dispatch_status(db, user, task)
        profile = db.get(EmployeeProfile, user.id)
        telemetry = None
        devices = db.scalars(
            select(Device).where(Device.last_user_id == user.id).order_by(Device.last_seen_at.desc())
        ).all()
        if devices:
            t = db.get(DeviceTelemetry, devices[0].id)
            if t:
                telemetry = {
                    "device_id": devices[0].id,
                    "battery_percent": t.battery_percent,
                    "connectivity": t.connectivity,
                    "last_location_id": t.last_location_id,
                    "updated_at": t.updated_at.isoformat(),
                }
        row["full_name"] = profile.full_name if profile else user.username
        row["device"] = telemetry
        rows.append(row)
    return {"workers": rows}


@router.post("/ops/dispatch/tasks/{task_id}/broadcast")
def dispatch_broadcast(
    task_id: str,
    req: BroadcastRequest,
    who=Depends(ops_manager),
    db: Session = Depends(get_db),
):
    try:
        with db.begin():
            task = db.get(PickTask, task_id)
            if not task:
                raise HTTPException(404, "Task not found")
            return broadcast_task(db, task, ttl_seconds=req.ttl_seconds)
    except OpsError as exc:
        fail(exc)


@router.get("/ops/dispatch/me/offers")
def dispatch_my_offers(who=Depends(ops_actor), db: Session = Depends(get_db)):
    user, _ = who
    with db.begin():
        offers = my_open_offers(db, user.id)
        return {
            "offers": [
                {
                    "offer_id": offer.id,
                    "task_id": offer.task_id,
                    "offered_at": offer.offered_at.isoformat(),
                    "expires_at": offer.expires_at.isoformat() if offer.expires_at else None,
                    "task": task_snapshot(db, db.get(PickTask, offer.task_id)),
                }
                for offer in offers
            ]
        }


@router.post("/ops/dispatch/tasks/{task_id}/claim")
def dispatch_claim(task_id: str, who=Depends(ops_actor), db: Session = Depends(get_db)):
    user, device = who
    try:
        with db.begin():
            task = db.get(PickTask, task_id)
            if not task:
                raise HTTPException(404, "Task not found")
            claimed = claim_task(db, task, user.id, device.id)
            return {"task": task_snapshot(db, claimed)}
    except OpsError as exc:
        fail(exc)


@router.post("/ops/dispatch/tasks/{task_id}/assign")
def dispatch_assign(
    task_id: str,
    req: DirectAssignRequest,
    who=Depends(ops_manager),
    db: Session = Depends(get_db),
):
    manager, _ = who
    try:
        with db.begin():
            task = db.get(PickTask, task_id)
            if not task:
                raise HTTPException(404, "Task not found")
            assigned = direct_assign_task(
                db,
                task,
                user_id=req.user_id,
                manager_id=manager.id,
                device_id=req.device_id,
                reason=req.reason,
            )
            return {"task": task_snapshot(db, assigned)}
    except OpsError as exc:
        fail(exc)


@router.post("/ops/qualifications")
def qualification_grant(
    req: QualificationRequest,
    who=Depends(ops_manager),
    db: Session = Depends(get_db),
):
    manager, _ = who
    try:
        with db.begin():
            row = grant_qualification(db, req.user_id, req.qualification, manager.id)
            return {
                "user_id": row.user_id,
                "qualification": row.qualification,
                "active": row.active,
            }
    except OpsError as exc:
        fail(exc)


@router.post("/ops/tasks/{task_id}/bags")
def bag_close(
    task_id: str,
    req: BagCloseRequest,
    who=Depends(ops_actor),
    db: Session = Depends(get_db),
):
    user, _ = who
    try:
        with db.begin():
            task = db.get(PickTask, task_id)
            if not task:
                raise HTTPException(404, "Task not found")
            bag = close_order_bag(db, task, user.id, req.spoo_code)
            return {
                "bag_id": bag.id,
                "bag_no": bag.bag_no,
                "spoo_last4": bag.spoo_code[-4:],
                "closed_at": bag.closed_at.isoformat(),
            }
    except OpsError as exc:
        fail(exc)


@router.post("/ops/tasks/{task_id}/finish-picking")
def finish_picking(task_id: str, who=Depends(ops_actor), db: Session = Depends(get_db)):
    user, _ = who
    try:
        with db.begin():
            task = db.get(PickTask, task_id)
            if not task:
                raise HTTPException(404, "Task not found")
            return finalize_pick_session(db, task, user.id)
    except OpsError as exc:
        fail(exc)


@router.get("/ops/orders/{order_id}/summary")
def order_summary(order_id: str, who=Depends(ops_actor), db: Session = Depends(get_db)):
    try:
        return order_completion_summary(db, order_id)
    except OpsError as exc:
        fail(exc)


@router.get("/ops/orders/search")
def orders_search(
    q: str | None = None,
    order_id: str | None = None,
    spoo: str | None = None,
    username: str | None = None,
    from_at: datetime | None = Query(default=None, alias="from"),
    to_at: datetime | None = Query(default=None, alias="to"),
    limit: int = Query(default=100, ge=1, le=500),
    who=Depends(ops_manager),
    db: Session = Depends(get_db),
):
    try:
        rows = search_orders(
            db,
            q=q,
            order_id=order_id,
            spoo=spoo,
            username=username,
            from_at=from_at,
            to_at=to_at,
            limit=limit,
        )
        return {"count": len(rows), "orders": rows}
    except OpsError as exc:
        fail(exc)


@router.get("/ops/availability/holds")
def availability_holds(
    site_id: str = "DEMO",
    who=Depends(ops_manager),
    db: Session = Depends(get_db),
):
    return {"holds": list_effective_holds(db, site_id)}


@router.post("/ops/availability/holds")
def availability_create_hold(
    req: HoldCreateRequest,
    who=Depends(ops_manager),
    db: Session = Depends(get_db),
):
    manager, _ = who
    try:
        with db.begin():
            hold = create_hold(
                db,
                site_id=req.site_id,
                scope_type=req.scope_type,
                scope_value=req.scope_value,
                reason=req.reason,
                notes=req.notes,
                hard_stop=req.hard_stop,
                starts_at=req.starts_at,
                expires_at=req.expires_at,
                created_by_user_id=manager.id,
            )
            impact = hold_impact(db, hold)
            return {
                "hold": {
                    "id": hold.id,
                    "scope_type": hold.scope_type,
                    "scope_value": hold.scope_value,
                    "reason": hold.reason,
                    "hard_stop": hold.hard_stop,
                    "starts_at": hold.starts_at.isoformat(),
                    "expires_at": hold.expires_at.isoformat() if hold.expires_at else None,
                },
                "impact": impact,
            }
    except OpsError as exc:
        fail(exc)


@router.post("/ops/availability/holds/{hold_id}/resume")
def availability_resume_hold(
    hold_id: str,
    who=Depends(ops_manager),
    db: Session = Depends(get_db),
):
    manager, _ = who
    with db.begin():
        hold = db.get(FulfillmentHold, hold_id)
        if not hold:
            raise HTTPException(404, "Hold not found")
        resume_hold(db, hold, manager.id)
        return {"id": hold.id, "active": hold.active, "ended_at": hold.ended_at.isoformat()}


@router.get("/ops/availability/holds/{hold_id}/impact")
def availability_hold_impact(
    hold_id: str,
    who=Depends(ops_manager),
    db: Session = Depends(get_db),
):
    hold = db.get(FulfillmentHold, hold_id)
    if not hold:
        raise HTTPException(404, "Hold not found")
    return hold_impact(db, hold)


@router.get("/ops/catalog/{product_id}/orderability")
def catalog_orderability(product_id: str, db: Session = Depends(get_db)):
    try:
        return product_orderability(db, product_id)
    except OpsError as exc:
        fail(exc)


@router.post("/ops/tasks/{task_id}/skip")
def pick_skip(
    task_id: str,
    req: PickExceptionRequest,
    who=Depends(ops_actor),
    db: Session = Depends(get_db),
):
    user, device = who
    try:
        with db.begin():
            task = db.get(PickTask, task_id)
            item = db.get(PickTaskItem, req.task_item_id)
            if not task or not item:
                raise HTTPException(404, "Task or item not found")
            result = skip_task_item(
                db,
                task=task,
                item=item,
                event_id=req.event_id,
                client_seq=req.client_seq,
                user_id=user.id,
                device_id=device.id,
                reason=req.reason,
            )
            result["snapshot"] = task_snapshot(db, task)
            return result
    except OpsError as exc:
        fail(exc)


@router.post("/ops/tasks/{task_id}/damaged")
def pick_damaged(
    task_id: str,
    req: PickExceptionRequest,
    who=Depends(ops_actor),
    db: Session = Depends(get_db),
):
    user, device = who
    try:
        with db.begin():
            task = db.get(PickTask, task_id)
            item = db.get(PickTaskItem, req.task_item_id)
            if not task or not item:
                raise HTTPException(404, "Task or item not found")
            result = damage_task_item(
                db,
                task=task,
                item=item,
                event_id=req.event_id,
                client_seq=req.client_seq,
                user_id=user.id,
                device_id=device.id,
                qty=req.qty,
                reason=req.reason,
            )
            result["snapshot"] = task_snapshot(db, task)
            return result
    except OpsError as exc:
        fail(exc)


@router.get("/ops/inventory/alerts")
def inventory_alerts(
    status: str = "OPEN",
    who=Depends(ops_manager),
    db: Session = Depends(get_db),
):
    rows = db.scalars(
        select(InventoryAlert)
        .where(InventoryAlert.status == status.upper())
        .order_by(InventoryAlert.created_at.desc())
        .limit(200)
    ).all()
    return {
        "alerts": [
            {
                "id": row.id,
                "type": row.alert_type,
                "product_id": row.product_id,
                "location_id": row.location_id,
                "severity": row.severity,
                "status": row.status,
                "details": row.details_json,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ]
    }


@router.get("/ops/replenishment")
def replenishment_queue(
    status: str | None = None,
    who=Depends(ops_manager),
    db: Session = Depends(get_db),
):
    query = select(ReplenishmentTask).order_by(ReplenishmentTask.created_at)
    if status:
        query = query.where(ReplenishmentTask.status == status.upper())
    rows = db.scalars(query.limit(200)).all()
    return {
        "tasks": [
            {
                "id": row.id,
                "product_id": row.product_id,
                "source_location_id": row.source_location_id,
                "destination_location_id": row.destination_location_id,
                "qty": row.qty,
                "status": row.status,
                "trigger": row.trigger,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ]
    }


@router.get("/ops/performance")
def performance_dashboard(
    from_at: datetime | None = Query(default=None, alias="from"),
    to_at: datetime | None = Query(default=None, alias="to"),
    who=Depends(ops_manager),
    db: Session = Depends(get_db),
):
    end = to_at or datetime.now(timezone.utc)
    start = from_at or datetime(end.year, end.month, 1, tzinfo=timezone.utc)
    return {
        "from": start.isoformat(),
        "to": end.isoformat(),
        "rows": performance_rows(db, start, end),
        "policy_note": (
            "Metrics are factual operational indicators. Role or pay changes are not automatic; "
            "they require an explicit human review and approved payroll/role action."
        ),
    }


@router.get("/ops/slotting/suggestions")
def slotting(
    days: int = Query(default=30, ge=1, le=365),
    limit: int = Query(default=20, ge=1, le=100),
    who=Depends(ops_manager),
    db: Session = Depends(get_db),
):
    return {
        "days": days,
        "suggestions": slotting_suggestions(db, days=days, limit=limit),
        "automatic_move": False,
    }


@router.post("/ops/devices/telemetry")
def device_telemetry(
    req: DeviceTelemetryRequest,
    who=Depends(ops_actor),
    db: Session = Depends(get_db),
):
    _, device = who
    with db.begin():
        row = update_device_telemetry(
            db,
            device.id,
            battery_percent=req.battery_percent,
            connectivity=req.connectivity,
            last_location_id=req.last_location_id,
        )
        return {
            "device_id": row.device_id,
            "battery_percent": row.battery_percent,
            "connectivity": row.connectivity,
            "last_location_id": row.last_location_id,
            "updated_at": row.updated_at.isoformat(),
        }


@router.post("/ops/shipments")
def shipment_create(
    req: ShipmentCreateRequest,
    who=Depends(ops_manager),
    db: Session = Depends(get_db),
):
    manager, _ = who
    try:
        with db.begin():
            shipment = create_shipment(
                db,
                label=req.label,
                shipment_type=req.shipment_type,
                storage_domain=req.storage_domain,
                lines=[line.model_dump() for line in req.lines],
                created_by_user_id=manager.id,
                target_stow_minutes=req.target_stow_minutes,
            )
            return shipment_payload(db, shipment)
    except OpsError as exc:
        fail(exc)


@router.get("/ops/shipments")
def shipment_list(
    status: str | None = None,
    who=Depends(ops_manager),
    db: Session = Depends(get_db),
):
    query = select(Shipment).order_by(Shipment.created_at.desc())
    if status:
        query = query.where(Shipment.status == status.upper())
    rows = db.scalars(query.limit(200)).all()
    return {"shipments": [shipment_payload(db, row) for row in rows]}


@router.get("/ops/shipments/{shipment_id}")
def shipment_get(
    shipment_id: str,
    who=Depends(ops_actor),
    db: Session = Depends(get_db),
):
    shipment = db.get(Shipment, shipment_id)
    if not shipment:
        raise HTTPException(404, "Shipment not found")
    return shipment_payload(db, shipment)


@router.post("/ops/shipments/{shipment_id}/dock-check-in")
def shipment_dock(
    shipment_id: str,
    req: DockCheckInRequest,
    who=Depends(ops_actor),
    db: Session = Depends(get_db),
):
    from .services.ops_platform import dock_check_in
    try:
        with db.begin():
            shipment = db.get(Shipment, shipment_id)
            if not shipment:
                raise HTTPException(404, "Shipment not found")
            return shipment_payload(db, dock_check_in(db, shipment, req.dock_ref))
    except OpsError as exc:
        fail(exc)


@router.post("/ops/shipments/{shipment_id}/open")
def shipment_open(
    shipment_id: str,
    who=Depends(ops_actor),
    db: Session = Depends(get_db),
):
    user, device = who
    try:
        with db.begin():
            shipment = db.get(Shipment, shipment_id)
            if not shipment:
                raise HTTPException(404, "Shipment not found")
            session = open_shipment_receiving(
                db,
                shipment=shipment,
                user_id=user.id,
                device_id=device.id,
            )
            return {
                "session_id": session.id,
                "shipment": shipment_payload(db, shipment),
            }
    except OpsError as exc:
        fail(exc)


@router.post("/ops/shipments/{shipment_id}/receive")
def shipment_receive(
    shipment_id: str,
    req: ShipmentReceiveRequest,
    who=Depends(ops_actor),
    db: Session = Depends(get_db),
):
    user, device = who
    try:
        with db.begin():
            shipment = db.get(Shipment, shipment_id)
            if not shipment:
                raise HTTPException(404, "Shipment not found")
            from .models_ops import ReceivingSession
            session = db.scalar(
                select(ReceivingSession)
                .where(
                    ReceivingSession.shipment_id == shipment_id,
                    ReceivingSession.user_id == user.id,
                    ReceivingSession.device_id == device.id,
                    ReceivingSession.status == "OPEN",
                )
                .order_by(ReceivingSession.started_at.desc())
            )
            if not session:
                raise OpsError("Open the shipment before receiving", "NO_OPEN_RECEIVING_SESSION")
            return receive_shipment_line(
                db,
                shipment=shipment,
                session=session,
                event_id=req.event_id,
                product_id=req.product_id,
                good_qty=req.good_qty,
                damaged_qty=req.damaged_qty,
                lot_code=req.lot_code,
                expires_on=req.expires_on,
            )
    except OpsError as exc:
        fail(exc)


@router.post("/ops/shipments/{shipment_id}/complete-receive")
def shipment_receive_complete(
    shipment_id: str,
    who=Depends(ops_actor),
    db: Session = Depends(get_db),
):
    user, device = who
    try:
        with db.begin():
            shipment = db.get(Shipment, shipment_id)
            if not shipment:
                raise HTTPException(404, "Shipment not found")
            from .models_ops import ReceivingSession
            session = db.scalar(
                select(ReceivingSession)
                .where(
                    ReceivingSession.shipment_id == shipment_id,
                    ReceivingSession.user_id == user.id,
                    ReceivingSession.device_id == device.id,
                    ReceivingSession.status == "OPEN",
                )
                .order_by(ReceivingSession.started_at.desc())
            )
            if not session:
                raise OpsError("No open receiving session", "NO_OPEN_RECEIVING_SESSION")
            return complete_receiving(db, shipment, session)
    except OpsError as exc:
        fail(exc)


@router.get("/ops/stow/{task_id}/recommendations")
def stow_recommendations(
    task_id: str,
    who=Depends(ops_actor),
    db: Session = Depends(get_db),
):
    task = db.get(StowTask, task_id)
    if not task:
        raise HTTPException(404, "Stow task not found")
    shipment = db.get(Shipment, task.shipment_id)
    return {
        "task_id": task.id,
        "recommendations": recommend_stow_locations(db, shipment, task.product_id, 10),
    }


@router.post("/ops/stow/{task_id}/complete")
def stow_complete(
    task_id: str,
    req: StowCompleteRequest,
    who=Depends(ops_actor),
    db: Session = Depends(get_db),
):
    user, device = who
    try:
        with db.begin():
            task = db.get(StowTask, task_id)
            if not task:
                raise HTTPException(404, "Stow task not found")
            return complete_stow_task(
                db,
                task=task,
                destination_location_id=req.destination_location_id,
                user_id=user.id,
                device_id=device.id,
                event_id=req.event_id,
            )
    except OpsError as exc:
        fail(exc)
