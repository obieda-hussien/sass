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
    PayrollPolicy,
    AdminAuditEvent,
    ShiftAssignment,
    ShiftTemplate,
    LeaveRequest,
    OvertimeRequest,
    Shipment,
    StowTask,
    WorkerQualification,
    WorkerDispatchProfile,
    WarehouseEdge,
    WarehouseNode,
)
from .security import authenticate_access
from .services.ops_optimization import (
    create_cycle_count_from_alert,
    create_warehouse_node,
    evaluate_guard_rules,
    expiry_risk,
    handover_pick_task,
    incident_center,
    location_capacity_snapshot,
    optimize_task_route,
    set_guard_rule,
    set_location_operational_profile,
    set_worker_dispatch_profile,
    simulate_order_route,
    upsert_warehouse_edge,
    warehouse_heatmap,
)
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
    decline_task_offer,
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
from .services.governance import (
    GovernanceError,
    assign_shift,
    audit_event,
    auto_clock_in,
    auto_clock_out,
    create_leave_request,
    create_overtime_request,
    create_shift_template,
    effective_permissions,
    end_break,
    has_permission,
    require_permission,
    review_leave_request,
    review_overtime_request,
    roster,
    set_role_permission,
    set_user_permission,
    start_break,
)
from .services.replenishment import (
    ReplenishmentError,
    assign as assign_replenishment,
    cancel as cancel_replenishment,
    claim as claim_replenishment,
    complete as complete_replenishment,
    confirm_item as confirm_replenishment_item,
    generate_candidates as generate_replenishment_candidates,
    queue as replenishment_queue_v04,
    scan_destination as scan_replenishment_destination,
    scan_source as scan_replenishment_source,
    task_payload as replenishment_task_payload,
)
from .services.picking import task_snapshot
from .services.workforce import MANAGER_ROLES


router = APIRouter(tags=["operations-v0.4"])


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
    if user.must_change_password:
        db.commit()
        raise HTTPException(
            428,
            {
                "code": "PASSWORD_CHANGE_REQUIRED",
                "message": "Change the temporary PIN before using warehouse tools.",
            },
        )
    db.commit()
    return user, device


def ops_manager(
    who=Depends(ops_actor),
    db: Session = Depends(get_db),
) -> tuple[User, Device]:
    user, device = who
    try:
        require_permission(db, user, "operations.manage")
        db.commit()
    except GovernanceError as exc:
        raise HTTPException(403, {"code": exc.code, "message": str(exc)})
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


class PayrollPolicyRequest(BaseModel):
    late_deduction_cents_per_minute: int = Field(default=0, ge=0)
    early_leave_deduction_cents_per_minute: int = Field(default=0, ge=0)
    auto_apply_attendance_deductions: bool = False


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
    lines: list[ShipmentLineInput] = Field(default_factory=list)


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


class DispatchProfileRequest(BaseModel):
    home_domain: str | None = None
    allowed_domains: list[str] = Field(default_factory=list)


class LocationOperationalProfileRequest(BaseModel):
    node_id: str | None = None
    capacity_units: int | None = Field(default=None, ge=0)
    average_pick_seconds: float | None = Field(default=None, gt=0)
    route_sequence_override: int | None = None


class WarehouseNodeRequest(BaseModel):
    id: str
    site_id: str = "DEMO"
    name: str
    node_type: str = "PICK"
    domain: str | None = None
    aisle: int | None = None
    x_m: float | None = None
    y_m: float | None = None


class WarehouseEdgeRequest(BaseModel):
    site_id: str = "DEMO"
    from_node_id: str
    to_node_id: str
    distance_m: float = Field(gt=0)
    one_way: bool = False
    congestion_factor: float = Field(default=1.0, gt=0)


class HandoverRequest(BaseModel):
    to_user_id: str
    to_device_id: str | None = None
    reason: str = "OPERATIONAL_HANDOVER"


class SimulationLineRequest(BaseModel):
    product_id: str
    qty: int = Field(default=1, gt=0)


class OrderSimulationRequest(BaseModel):
    lines: list[SimulationLineRequest] = Field(default_factory=list)
    start_location_id: str | None = None


class GuardRuleRequest(BaseModel):
    enabled: bool
    config: dict[str, Any] = Field(default_factory=dict)


class CycleCountAssignRequest(BaseModel):
    user_id: str


class ShiftTemplateCreateRequest(BaseModel):
    site_id: str = "DEMO"
    name: str = Field(min_length=2, max_length=100)
    start_minute: int = Field(ge=0, le=1439)
    end_minute: int = Field(ge=0, le=1439)
    timezone_name: str = "Africa/Cairo"
    break_minutes: int = Field(default=0, ge=0, le=480)
    grace_minutes: int = Field(default=10, ge=0, le=240)


class ShiftAssignmentRequest(BaseModel):
    user_id: str
    shift_template_id: str
    shift_date: date
    notes: str | None = None


class BreakStartRequest(BaseModel):
    break_type: str = "REST"
    paid: bool = True


class LeaveCreateRequest(BaseModel):
    leave_type: str = "ANNUAL"
    starts_on: date
    ends_on: date
    reason: str | None = None


class LeaveReviewRequest(BaseModel):
    approved: bool


class OvertimeCreateRequest(BaseModel):
    requested_minutes: int = Field(gt=0, le=1440)
    shift_assignment_id: str | None = None
    reason: str | None = None


class OvertimeReviewRequest(BaseModel):
    approved_minutes: int = Field(ge=0, le=1440)


class PermissionGrantRequest(BaseModel):
    permission: str = Field(min_length=2, max_length=120)
    allowed: bool = True


class ReplenishmentAssignRequest(BaseModel):
    user_id: str
    priority: int | None = Field(default=None, ge=0, le=1000)


class ReplenishmentSourceRequest(BaseModel):
    event_id: str
    source_location_id: str


class ReplenishmentItemRequest(BaseModel):
    event_id: str
    barcode: str


class ReplenishmentDestinationRequest(BaseModel):
    event_id: str
    destination_location_id: str


class ReplenishmentCompleteRequest(BaseModel):
    event_id: str
    actual_qty: int = Field(gt=0)


class ReplenishmentCancelRequest(BaseModel):
    reason: str = Field(min_length=2, max_length=240)


class ReplenishmentGenerateRequest(BaseModel):
    low_stock_threshold: int = Field(default=3, ge=0, le=100000)
    target_qty: int = Field(default=12, ge=1, le=100000)
    max_new_tasks: int = Field(default=100, ge=1, le=1000)


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
                device_live = bool(row.get("device_live"))
                telemetry = {
                    "device_id": devices[0].id,
                    "battery_percent": t.battery_percent,
                    "connectivity": "ONLINE" if device_live else "OFFLINE",
                    "last_location_id": t.last_location_id,
                    "activity": t.activity if device_live else None,
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


@router.post("/ops/dispatch/tasks/{task_id}/reject")
def dispatch_reject(
    task_id: str,
    who=Depends(ops_actor),
    db: Session = Depends(get_db),
):
    user, device = who
    try:
        with db.begin():
            task = db.get(PickTask, task_id)
            if not task:
                raise HTTPException(404, "Task not found")
            return decline_task_offer(
                db,
                task,
                user_id=user.id,
                device_id=device.id,
                reason="ASSOCIATE_REJECTED",
            )
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


@router.get("/ops/dispatch/profiles/{user_id}")
def dispatch_profile_get(
    user_id: str,
    who=Depends(ops_manager),
    db: Session = Depends(get_db),
):
    if db.get(User, user_id) is None:
        raise HTTPException(404, "User not found")
    row = db.get(WorkerDispatchProfile, user_id)
    return {
        "user_id": user_id,
        "home_domain": row.home_domain if row else None,
        "allowed_domains": [] if row is None else __import__("json").loads(row.allowed_domains_json or "[]"),
    }


@router.put("/ops/dispatch/profiles/{user_id}")
def dispatch_profile_put(
    user_id: str,
    req: DispatchProfileRequest,
    who=Depends(ops_manager),
    db: Session = Depends(get_db),
):
    manager, _ = who
    if db.get(User, user_id) is None:
        raise HTTPException(404, "User not found")
    with db.begin():
        row = set_worker_dispatch_profile(
            db,
            user_id=user_id,
            home_domain=req.home_domain,
            allowed_domains=req.allowed_domains,
            manager_id=manager.id,
        )
        return {
            "user_id": row.user_id,
            "home_domain": row.home_domain,
            "allowed_domains": __import__("json").loads(row.allowed_domains_json or "[]"),
        }


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


@router.post("/ops/tasks/{task_id}/handover")
def task_handover(
    task_id: str,
    req: HandoverRequest,
    who=Depends(ops_manager),
    db: Session = Depends(get_db),
):
    manager, _ = who
    try:
        with db.begin():
            task = db.get(PickTask, task_id)
            if not task:
                raise HTTPException(404, "Task not found")
            row = handover_pick_task(
                db,
                task=task,
                to_user_id=req.to_user_id,
                manager_id=manager.id,
                reason=req.reason,
                to_device_id=req.to_device_id,
            )
            return {
                "handover_id": row.id,
                "task_id": row.task_id,
                "from_user_id": row.from_user_id,
                "to_user_id": row.to_user_id,
                "picked_units_before_handover": row.picked_units_before_handover,
                "created_at": row.created_at.isoformat(),
            }
    except ValueError as exc:
        raise HTTPException(409, str(exc))


@router.post("/ops/tasks/{task_id}/optimize-route")
def task_optimize_route(
    task_id: str,
    current_location_id: str | None = None,
    who=Depends(ops_actor),
    db: Session = Depends(get_db),
):
    user, _ = who
    with db.begin():
        task = db.get(PickTask, task_id)
        if not task:
            raise HTTPException(404, "Task not found")
        if user.role.upper() not in MANAGER_ROLES and task.assigned_user_id != user.id:
            raise HTTPException(403, "Task ownership required")
        return optimize_task_route(
            db,
            task,
            current_location_id=current_location_id,
            persist=True,
        )


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


@router.get("/ops/analytics/heatmap")
def analytics_heatmap(
    from_at: datetime | None = Query(default=None, alias="from"),
    to_at: datetime | None = Query(default=None, alias="to"),
    site_id: str = "DEMO",
    who=Depends(ops_manager),
    db: Session = Depends(get_db),
):
    end = to_at or datetime.now(timezone.utc)
    start = from_at or end.replace(hour=0, minute=0, second=0, microsecond=0)
    return {
        "from": start.isoformat(),
        "to": end.isoformat(),
        "rows": warehouse_heatmap(db, from_at=start, to_at=end, site_id=site_id),
    }


@router.get("/ops/expiry-risk")
def expiry_awareness(
    days: int = Query(default=7, ge=0, le=365),
    site_id: str = "DEMO",
    who=Depends(ops_manager),
    db: Session = Depends(get_db),
):
    return {"days": days, "lots": expiry_risk(db, days=days, site_id=site_id)}


@router.post("/ops/simulation/order")
def order_simulation(
    req: OrderSimulationRequest,
    who=Depends(ops_manager),
    db: Session = Depends(get_db),
):
    return simulate_order_route(
        db,
        lines=[line.model_dump() for line in req.lines],
        start_location_id=req.start_location_id,
    )


@router.get("/ops/incidents")
def incidents(
    site_id: str = "DEMO",
    who=Depends(ops_manager),
    db: Session = Depends(get_db),
):
    return incident_center(db, site_id=site_id)


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


@router.get("/ops/payroll-policy/{user_id}")
def payroll_policy_get(
    user_id: str,
    who=Depends(ops_manager),
    db: Session = Depends(get_db),
):
    if db.get(User, user_id) is None:
        raise HTTPException(404, "User not found")
    row = db.get(PayrollPolicy, user_id)
    return {
        "user_id": user_id,
        "late_deduction_cents_per_minute": row.late_deduction_cents_per_minute if row else 0,
        "early_leave_deduction_cents_per_minute": row.early_leave_deduction_cents_per_minute if row else 0,
        "auto_apply_attendance_deductions": row.auto_apply_attendance_deductions if row else False,
    }


@router.put("/ops/payroll-policy/{user_id}")
def payroll_policy_put(
    user_id: str,
    req: PayrollPolicyRequest,
    who=Depends(ops_manager),
    db: Session = Depends(get_db),
):
    manager, _ = who
    with db.begin():
        if db.get(User, user_id) is None:
            raise HTTPException(404, "User not found")
        row = db.get(PayrollPolicy, user_id)
        old_value = {
            "late_deduction_cents_per_minute": row.late_deduction_cents_per_minute if row else 0,
            "early_leave_deduction_cents_per_minute": row.early_leave_deduction_cents_per_minute if row else 0,
            "auto_apply_attendance_deductions": row.auto_apply_attendance_deductions if row else False,
        }
        if row is None:
            row = PayrollPolicy(user_id=user_id)
            db.add(row)
        row.late_deduction_cents_per_minute = req.late_deduction_cents_per_minute
        row.early_leave_deduction_cents_per_minute = req.early_leave_deduction_cents_per_minute
        row.auto_apply_attendance_deductions = req.auto_apply_attendance_deductions
        row.updated_by_user_id = manager.id
        db.flush()
        audit_event(
            db,
            actor_user_id=manager.id,
            action="UPDATE_PAYROLL_POLICY",
            entity_type="PAYROLL_POLICY",
            entity_id=user_id,
            old_value=old_value,
            new_value={
                "late_deduction_cents_per_minute": row.late_deduction_cents_per_minute,
                "early_leave_deduction_cents_per_minute": row.early_leave_deduction_cents_per_minute,
                "auto_apply_attendance_deductions": row.auto_apply_attendance_deductions,
            },
        )
        return {
            "user_id": user_id,
            "late_deduction_cents_per_minute": row.late_deduction_cents_per_minute,
            "early_leave_deduction_cents_per_minute": row.early_leave_deduction_cents_per_minute,
            "auto_apply_attendance_deductions": row.auto_apply_attendance_deductions,
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


@router.get("/ops/locations/{location_id}/capacity")
def location_capacity(
    location_id: str,
    who=Depends(ops_manager),
    db: Session = Depends(get_db),
):
    if db.get(__import__("app.models", fromlist=["Location"]).Location, location_id) is None:
        raise HTTPException(404, "Location not found")
    return location_capacity_snapshot(db, location_id)


@router.put("/ops/locations/{location_id}/operational-profile")
def location_operational_profile_put(
    location_id: str,
    req: LocationOperationalProfileRequest,
    who=Depends(ops_manager),
    db: Session = Depends(get_db),
):
    try:
        with db.begin():
            row = set_location_operational_profile(
                db,
                location_id=location_id,
                node_id=req.node_id,
                capacity_units=req.capacity_units,
                average_pick_seconds=req.average_pick_seconds,
                route_sequence_override=req.route_sequence_override,
            )
            return {
                "location_id": row.location_id,
                "node_id": row.node_id,
                "capacity": location_capacity_snapshot(db, location_id),
                "average_pick_seconds": row.average_pick_seconds,
                "route_sequence_override": row.route_sequence_override,
            }
    except ValueError as exc:
        raise HTTPException(404, str(exc))


@router.post("/ops/topology/nodes")
def topology_node_put(
    req: WarehouseNodeRequest,
    who=Depends(ops_manager),
    db: Session = Depends(get_db),
):
    with db.begin():
        row = create_warehouse_node(
            db,
            node_id=req.id,
            site_id=req.site_id,
            name=req.name,
            node_type=req.node_type,
            domain=req.domain,
            aisle=req.aisle,
            x_m=req.x_m,
            y_m=req.y_m,
        )
        return {
            "id": row.id,
            "site_id": row.site_id,
            "name": row.name,
            "node_type": row.node_type,
            "domain": row.domain,
            "aisle": row.aisle,
            "x_m": row.x_m,
            "y_m": row.y_m,
        }


@router.post("/ops/topology/edges")
def topology_edge_put(
    req: WarehouseEdgeRequest,
    who=Depends(ops_manager),
    db: Session = Depends(get_db),
):
    try:
        with db.begin():
            row = upsert_warehouse_edge(
                db,
                site_id=req.site_id,
                from_node_id=req.from_node_id,
                to_node_id=req.to_node_id,
                distance_m=req.distance_m,
                one_way=req.one_way,
                congestion_factor=req.congestion_factor,
            )
            return {
                "id": row.id,
                "from_node_id": row.from_node_id,
                "to_node_id": row.to_node_id,
                "distance_m": row.distance_m,
                "one_way": row.one_way,
                "congestion_factor": row.congestion_factor,
            }
    except ValueError as exc:
        raise HTTPException(409, str(exc))


@router.get("/ops/topology")
def topology_get(
    site_id: str = "DEMO",
    who=Depends(ops_manager),
    db: Session = Depends(get_db),
):
    nodes = db.scalars(select(WarehouseNode).where(WarehouseNode.site_id == site_id)).all()
    edges = db.scalars(select(WarehouseEdge).where(WarehouseEdge.site_id == site_id)).all()
    return {
        "nodes": [
            {
                "id": n.id, "name": n.name, "node_type": n.node_type,
                "domain": n.domain, "aisle": n.aisle, "x_m": n.x_m, "y_m": n.y_m,
            }
            for n in nodes
        ],
        "edges": [
            {
                "id": e.id, "from_node_id": e.from_node_id, "to_node_id": e.to_node_id,
                "distance_m": e.distance_m, "one_way": e.one_way,
                "congestion_factor": e.congestion_factor,
            }
            for e in edges
        ],
    }


@router.put("/ops/guards/{domain}/{rule_type}")
def guard_rule_put(
    domain: str,
    rule_type: str,
    req: GuardRuleRequest,
    who=Depends(ops_manager),
    db: Session = Depends(get_db),
):
    manager, _ = who
    with db.begin():
        row = set_guard_rule(
            db,
            site_id="DEMO",
            domain=domain,
            rule_type=rule_type,
            enabled=req.enabled,
            config=req.config,
            manager_id=manager.id,
        )
        evaluation = evaluate_guard_rules(db, site_id="DEMO")
        return {
            "id": row.id,
            "domain": row.domain,
            "rule_type": row.rule_type,
            "enabled": row.enabled,
            "evaluation": evaluation,
        }


@router.post("/ops/guards/evaluate")
def guard_evaluate(
    who=Depends(ops_manager),
    db: Session = Depends(get_db),
):
    with db.begin():
        return {"results": evaluate_guard_rules(db, site_id="DEMO")}


@router.post("/ops/inventory/alerts/{alert_id}/create-cycle-count")
def alert_create_cycle_count(
    alert_id: str,
    req: CycleCountAssignRequest,
    who=Depends(ops_manager),
    db: Session = Depends(get_db),
):
    manager, _ = who
    try:
        with db.begin():
            session = create_cycle_count_from_alert(
                db,
                alert_id=alert_id,
                user_id=req.user_id,
                manager_id=manager.id,
            )
            return {
                "session_id": session.id,
                "location_id": session.location_id,
                "user_id": session.user_id,
                "status": session.status,
            }
    except ValueError as exc:
        raise HTTPException(409, str(exc))


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


# --- v0.4 governance, rota and replenishment ---------------------------------

@router.get("/ops/permissions/me")
def permissions_me(
    who=Depends(ops_actor),
    db: Session = Depends(get_db),
):
    user, _ = who
    return effective_permissions(db, user)


@router.put("/ops/permissions/roles/{role}")
def permission_role_put(
    role: str,
    req: PermissionGrantRequest,
    who=Depends(ops_actor),
    db: Session = Depends(get_db),
):
    actor, _ = who
    try:
        require_permission(db, actor, "permissions.manage")
        db.commit()
        with db.begin():
            row = set_role_permission(
                db,
                role=role,
                permission=req.permission,
                allowed=req.allowed,
                actor_user_id=actor.id,
            )
            return {"role": row.role, "permission": row.permission, "allowed": row.allowed}
    except GovernanceError as exc:
        raise HTTPException(403 if exc.code == "PERMISSION_DENIED" else 409, {"code": exc.code, "message": str(exc)})


@router.put("/ops/permissions/users/{user_id}")
def permission_user_put(
    user_id: str,
    req: PermissionGrantRequest,
    who=Depends(ops_actor),
    db: Session = Depends(get_db),
):
    actor, _ = who
    try:
        require_permission(db, actor, "permissions.manage")
        db.commit()
        with db.begin():
            row = set_user_permission(
                db,
                user_id=user_id,
                permission=req.permission,
                allowed=req.allowed,
                actor_user_id=actor.id,
            )
            return {"user_id": row.user_id, "permission": row.permission, "allowed": row.allowed}
    except GovernanceError as exc:
        raise HTTPException(403 if exc.code == "PERMISSION_DENIED" else 409, {"code": exc.code, "message": str(exc)})


@router.get("/ops/audit")
def admin_audit(
    entity_type: str | None = None,
    entity_id: str | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
    who=Depends(ops_actor),
    db: Session = Depends(get_db),
):
    actor, _ = who
    try:
        require_permission(db, actor, "audit.read")
    except GovernanceError as exc:
        raise HTTPException(403, {"code": exc.code, "message": str(exc)})
    query = select(AdminAuditEvent).order_by(AdminAuditEvent.created_at.desc())
    if entity_type:
        query = query.where(AdminAuditEvent.entity_type == entity_type.strip().upper())
    if entity_id:
        query = query.where(AdminAuditEvent.entity_id == entity_id)
    rows = db.scalars(query.limit(limit)).all()
    return {
        "events": [
            {
                "id": row.id,
                "actor_user_id": row.actor_user_id,
                "action": row.action,
                "entity_type": row.entity_type,
                "entity_id": row.entity_id,
                "field_name": row.field_name,
                "old_value_json": row.old_value_json,
                "new_value_json": row.new_value_json,
                "reason": row.reason,
                "request_id": row.request_id,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ]
    }


@router.post("/ops/shifts/templates")
def shift_template_create(
    req: ShiftTemplateCreateRequest,
    who=Depends(ops_actor),
    db: Session = Depends(get_db),
):
    actor, _ = who
    try:
        require_permission(db, actor, "shifts.manage")
        db.commit()
        with db.begin():
            row = create_shift_template(
                db,
                site_id=req.site_id,
                name=req.name,
                start_minute=req.start_minute,
                end_minute=req.end_minute,
                timezone_name=req.timezone_name,
                break_minutes=req.break_minutes,
                grace_minutes=req.grace_minutes,
                actor_user_id=actor.id,
            )
            return {
                "id": row.id,
                "site_id": row.site_id,
                "name": row.name,
                "start_minute": row.start_minute,
                "end_minute": row.end_minute,
                "timezone_name": row.timezone_name,
                "break_minutes": row.break_minutes,
                "grace_minutes": row.grace_minutes,
                "active": row.active,
            }
    except GovernanceError as exc:
        raise HTTPException(403 if exc.code == "PERMISSION_DENIED" else 409, {"code": exc.code, "message": str(exc)})


@router.get("/ops/shifts/templates")
def shift_template_list(
    active_only: bool = True,
    who=Depends(ops_actor),
    db: Session = Depends(get_db),
):
    actor, _ = who
    if not (has_permission(db, actor, "shifts.manage") or has_permission(db, actor, "operations.read")):
        raise HTTPException(403, "Shift read permission required")
    query = select(ShiftTemplate).order_by(ShiftTemplate.site_id, ShiftTemplate.start_minute)
    if active_only:
        query = query.where(ShiftTemplate.active == True)  # noqa: E712
    rows = db.scalars(query).all()
    return {
        "templates": [
            {
                "id": row.id,
                "site_id": row.site_id,
                "name": row.name,
                "start_minute": row.start_minute,
                "end_minute": row.end_minute,
                "timezone_name": row.timezone_name,
                "break_minutes": row.break_minutes,
                "grace_minutes": row.grace_minutes,
                "active": row.active,
            }
            for row in rows
        ]
    }


@router.post("/ops/shifts/assignments")
def shift_assignment_create(
    req: ShiftAssignmentRequest,
    who=Depends(ops_actor),
    db: Session = Depends(get_db),
):
    actor, _ = who
    try:
        require_permission(db, actor, "shifts.manage")
        db.commit()
        with db.begin():
            row = assign_shift(
                db,
                user_id=req.user_id,
                shift_template_id=req.shift_template_id,
                shift_date=req.shift_date,
                actor_user_id=actor.id,
                notes=req.notes,
            )
            return {
                "id": row.id,
                "user_id": row.user_id,
                "shift_date": row.shift_date.isoformat(),
                "scheduled_start_at": row.scheduled_start_at.isoformat(),
                "scheduled_end_at": row.scheduled_end_at.isoformat(),
                "status": row.status,
            }
    except GovernanceError as exc:
        raise HTTPException(403 if exc.code == "PERMISSION_DENIED" else 409, {"code": exc.code, "message": str(exc)})


@router.get("/ops/shifts/roster")
def shift_roster(
    from_date: date = Query(alias="from"),
    to_date: date = Query(alias="to"),
    user_id: str | None = None,
    who=Depends(ops_actor),
    db: Session = Depends(get_db),
):
    actor, _ = who
    if actor.id != user_id and not (
        has_permission(db, actor, "shifts.manage") or has_permission(db, actor, "operations.read")
    ):
        raise HTTPException(403, "Shift read permission required")
    return {"assignments": roster(db, from_date=from_date, to_date=to_date, user_id=user_id)}


@router.post("/ops/shifts/clock-in/auto")
def shift_clock_in_auto(
    who=Depends(ops_actor),
    db: Session = Depends(get_db),
):
    user, _ = who
    try:
        with db.begin():
            return auto_clock_in(db, user_id=user.id)
    except (GovernanceError, OpsError) as exc:
        code = exc.code if hasattr(exc, "code") else "SHIFT_ERROR"
        raise HTTPException(409, {"code": code, "message": str(exc)})


@router.post("/ops/shifts/clock-out/auto")
def shift_clock_out_auto(
    who=Depends(ops_actor),
    db: Session = Depends(get_db),
):
    user, _ = who
    try:
        with db.begin():
            return auto_clock_out(db, user_id=user.id)
    except (GovernanceError, OpsError) as exc:
        code = exc.code if hasattr(exc, "code") else "SHIFT_ERROR"
        raise HTTPException(409, {"code": code, "message": str(exc)})


@router.post("/ops/breaks/start")
def break_start(
    req: BreakStartRequest,
    who=Depends(ops_actor),
    db: Session = Depends(get_db),
):
    user, _ = who
    try:
        with db.begin():
            row = start_break(db, user_id=user.id, break_type=req.break_type, paid=req.paid)
            return {
                "id": row.id,
                "break_type": row.break_type,
                "paid": row.paid,
                "started_at": row.started_at.isoformat(),
            }
    except GovernanceError as exc:
        raise HTTPException(409, {"code": exc.code, "message": str(exc)})


@router.post("/ops/breaks/end")
def break_end(
    who=Depends(ops_actor),
    db: Session = Depends(get_db),
):
    user, _ = who
    try:
        with db.begin():
            row = end_break(db, user_id=user.id)
            return {
                "id": row.id,
                "duration_minutes": row.duration_minutes,
                "ended_at": row.ended_at.isoformat() if row.ended_at else None,
            }
    except GovernanceError as exc:
        raise HTTPException(409, {"code": exc.code, "message": str(exc)})


@router.post("/ops/leave")
def leave_create(
    req: LeaveCreateRequest,
    who=Depends(ops_actor),
    db: Session = Depends(get_db),
):
    user, _ = who
    try:
        with db.begin():
            row = create_leave_request(
                db,
                user_id=user.id,
                leave_type=req.leave_type,
                starts_on=req.starts_on,
                ends_on=req.ends_on,
                reason=req.reason,
            )
            return {
                "id": row.id,
                "status": row.status,
                "starts_on": row.starts_on.isoformat(),
                "ends_on": row.ends_on.isoformat(),
            }
    except GovernanceError as exc:
        raise HTTPException(409, {"code": exc.code, "message": str(exc)})


@router.post("/ops/leave/{request_id}/review")
def leave_review(
    request_id: str,
    req: LeaveReviewRequest,
    who=Depends(ops_actor),
    db: Session = Depends(get_db),
):
    actor, _ = who
    try:
        require_permission(db, actor, "shifts.manage")
        db.commit()
        with db.begin():
            row = review_leave_request(
                db,
                request_id=request_id,
                approved=req.approved,
                reviewer_id=actor.id,
            )
            return {"id": row.id, "status": row.status}
    except GovernanceError as exc:
        raise HTTPException(403 if exc.code == "PERMISSION_DENIED" else 409, {"code": exc.code, "message": str(exc)})


@router.post("/ops/overtime")
def overtime_create(
    req: OvertimeCreateRequest,
    who=Depends(ops_actor),
    db: Session = Depends(get_db),
):
    user, _ = who
    try:
        with db.begin():
            row = create_overtime_request(
                db,
                user_id=user.id,
                requested_minutes=req.requested_minutes,
                shift_assignment_id=req.shift_assignment_id,
                reason=req.reason,
            )
            return {"id": row.id, "status": row.status, "requested_minutes": row.requested_minutes}
    except GovernanceError as exc:
        raise HTTPException(409, {"code": exc.code, "message": str(exc)})


@router.post("/ops/overtime/{request_id}/review")
def overtime_review(
    request_id: str,
    req: OvertimeReviewRequest,
    who=Depends(ops_actor),
    db: Session = Depends(get_db),
):
    actor, _ = who
    try:
        require_permission(db, actor, "shifts.manage")
        db.commit()
        with db.begin():
            row = review_overtime_request(
                db,
                request_id=request_id,
                approved_minutes=req.approved_minutes,
                reviewer_id=actor.id,
            )
            return {
                "id": row.id,
                "status": row.status,
                "approved_minutes": row.approved_minutes,
            }
    except GovernanceError as exc:
        raise HTTPException(403 if exc.code == "PERMISSION_DENIED" else 409, {"code": exc.code, "message": str(exc)})


@router.get("/ops/replenishment/queue")
def replenishment_queue_live(
    status: str | None = None,
    mine: bool = False,
    who=Depends(ops_actor),
    db: Session = Depends(get_db),
):
    user, _ = who
    can_manage = has_permission(db, user, "replenishment.manage")
    can_execute = has_permission(db, user, "replenishment.execute")
    if not (can_manage or can_execute):
        raise HTTPException(403, "Replenishment permission required")
    return {
        "tasks": replenishment_queue_v04(
            db,
            status=status,
            assigned_user_id=user.id if mine and not can_manage else None,
        )
    }


@router.post("/ops/replenishment/generate")
def replenishment_generate(
    req: ReplenishmentGenerateRequest,
    who=Depends(ops_actor),
    db: Session = Depends(get_db),
):
    actor, _ = who
    try:
        require_permission(db, actor, "replenishment.manage")
        db.commit()
        with db.begin():
            rows = generate_replenishment_candidates(
                db,
                low_stock_threshold=req.low_stock_threshold,
                target_qty=req.target_qty,
                max_new_tasks=req.max_new_tasks,
            )
            audit_event(
                db,
                actor_user_id=actor.id,
                action="GENERATE_REPLENISHMENT",
                entity_type="REPLENISHMENT_BATCH",
                entity_id=datetime.now(timezone.utc).isoformat(),
                new_value={"created_task_ids": [row.id for row in rows]},
            )
            return {"created": len(rows), "tasks": [replenishment_task_payload(db, row) for row in rows]}
    except GovernanceError as exc:
        raise HTTPException(403, {"code": exc.code, "message": str(exc)})


@router.post("/ops/replenishment/{task_id}/assign")
def replenishment_assign(
    task_id: str,
    req: ReplenishmentAssignRequest,
    who=Depends(ops_actor),
    db: Session = Depends(get_db),
):
    actor, _ = who
    try:
        require_permission(db, actor, "replenishment.manage")
        db.commit()
        with db.begin():
            task = db.get(ReplenishmentTask, task_id)
            if not task:
                raise HTTPException(404, "Replenishment task not found")
            row = assign_replenishment(
                db,
                task=task,
                user_id=req.user_id,
                manager_id=actor.id,
                priority=req.priority,
            )
            return replenishment_task_payload(db, row)
    except (GovernanceError, ReplenishmentError) as exc:
        code = exc.code
        raise HTTPException(403 if code == "PERMISSION_DENIED" else 409, {"code": code, "message": str(exc)})


@router.post("/ops/replenishment/{task_id}/claim")
def replenishment_claim(
    task_id: str,
    who=Depends(ops_actor),
    db: Session = Depends(get_db),
):
    user, device = who
    try:
        require_permission(db, user, "replenishment.execute")
        db.commit()
        with db.begin():
            task = db.get(ReplenishmentTask, task_id)
            if not task:
                raise HTTPException(404, "Replenishment task not found")
            row = claim_replenishment(db, task=task, user_id=user.id, device_id=device.id)
            return replenishment_task_payload(db, row)
    except (GovernanceError, ReplenishmentError) as exc:
        code = exc.code
        raise HTTPException(403 if code == "PERMISSION_DENIED" else 409, {"code": code, "message": str(exc)})


@router.post("/ops/replenishment/{task_id}/source")
def replenishment_source(
    task_id: str,
    req: ReplenishmentSourceRequest,
    who=Depends(ops_actor),
    db: Session = Depends(get_db),
):
    user, device = who
    try:
        require_permission(db, user, "replenishment.execute")
        db.commit()
        with db.begin():
            task = db.get(ReplenishmentTask, task_id)
            if not task:
                raise HTTPException(404, "Replenishment task not found")
            return scan_replenishment_source(
                db,
                task=task,
                event_id=req.event_id,
                user_id=user.id,
                device_id=device.id,
                source_location_id=req.source_location_id,
            )
    except (GovernanceError, ReplenishmentError) as exc:
        code = exc.code
        raise HTTPException(403 if code == "PERMISSION_DENIED" else 409, {"code": code, "message": str(exc)})


@router.post("/ops/replenishment/{task_id}/item")
def replenishment_item(
    task_id: str,
    req: ReplenishmentItemRequest,
    who=Depends(ops_actor),
    db: Session = Depends(get_db),
):
    user, device = who
    try:
        require_permission(db, user, "replenishment.execute")
        db.commit()
        with db.begin():
            task = db.get(ReplenishmentTask, task_id)
            if not task:
                raise HTTPException(404, "Replenishment task not found")
            return confirm_replenishment_item(
                db,
                task=task,
                event_id=req.event_id,
                user_id=user.id,
                device_id=device.id,
                barcode=req.barcode,
            )
    except (GovernanceError, ReplenishmentError) as exc:
        code = exc.code
        raise HTTPException(403 if code == "PERMISSION_DENIED" else 409, {"code": code, "message": str(exc)})


@router.post("/ops/replenishment/{task_id}/destination")
def replenishment_destination(
    task_id: str,
    req: ReplenishmentDestinationRequest,
    who=Depends(ops_actor),
    db: Session = Depends(get_db),
):
    user, device = who
    try:
        require_permission(db, user, "replenishment.execute")
        db.commit()
        with db.begin():
            task = db.get(ReplenishmentTask, task_id)
            if not task:
                raise HTTPException(404, "Replenishment task not found")
            return scan_replenishment_destination(
                db,
                task=task,
                event_id=req.event_id,
                user_id=user.id,
                device_id=device.id,
                destination_location_id=req.destination_location_id,
            )
    except (GovernanceError, ReplenishmentError) as exc:
        code = exc.code
        raise HTTPException(403 if code == "PERMISSION_DENIED" else 409, {"code": code, "message": str(exc)})


@router.post("/ops/replenishment/{task_id}/complete")
def replenishment_complete(
    task_id: str,
    req: ReplenishmentCompleteRequest,
    who=Depends(ops_actor),
    db: Session = Depends(get_db),
):
    user, device = who
    try:
        require_permission(db, user, "replenishment.execute")
        db.commit()
        with db.begin():
            task = db.get(ReplenishmentTask, task_id)
            if not task:
                raise HTTPException(404, "Replenishment task not found")
            return complete_replenishment(
                db,
                task=task,
                event_id=req.event_id,
                user_id=user.id,
                device_id=device.id,
                actual_qty=req.actual_qty,
            )
    except (GovernanceError, ReplenishmentError) as exc:
        code = exc.code
        raise HTTPException(403 if code == "PERMISSION_DENIED" else 409, {"code": code, "message": str(exc)})


@router.post("/ops/replenishment/{task_id}/cancel")
def replenishment_cancel(
    task_id: str,
    req: ReplenishmentCancelRequest,
    who=Depends(ops_actor),
    db: Session = Depends(get_db),
):
    actor, _ = who
    try:
        require_permission(db, actor, "replenishment.manage")
        db.commit()
        with db.begin():
            task = db.get(ReplenishmentTask, task_id)
            if not task:
                raise HTTPException(404, "Replenishment task not found")
            row = cancel_replenishment(db, task=task, manager_id=actor.id, reason=req.reason)
            return replenishment_task_payload(db, row)
    except (GovernanceError, ReplenishmentError) as exc:
        code = exc.code
        raise HTTPException(403 if code == "PERMISSION_DENIED" else 409, {"code": code, "message": str(exc)})
