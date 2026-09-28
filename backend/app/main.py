from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from .database import Base, engine, get_db
from .schema_migrations import migrate_schema
from . import models_ops as _models_ops  # register v0.3 tables before create_all
from .location_parser import parse_location
from .models import (
    AttendanceEntry, Barcode, Device, DowntimeSegment, EmployeeProfile, InventoryBalance, Location,
    Order, OrderLine, PasswordResetRequest, PayAdjustment, PerformanceEvent, SessionToken,
    CycleCountSession, OrderStatus, PickTask, Product, TaskStatus, UnpackSession, User,
)
from .schemas import (
    BOHMoveRequest, CancelRequest, CycleCountApplyRequest, CycleCountLineRequest, CycleCountStartRequest,
    DamageRequest, DowntimeRequest, HeartbeatRequest, InventoryMoveRequest, LoginRequest, OrderCreate,
    AttendanceCreateRequest, ChangePasswordRequest, EmployeeCreateRequest, EmployeeUpdateRequest,
    ForgotPasswordRequest, HandoffRequest, PayAdjustmentCreateRequest, PerformanceEventCreateRequest, PromotionRequest,
    PickScanRequest, ReceiveRequest, RecoveryStowRequest, RefreshRequest, RejectOfferRequest,
    ShortPickRequest, StageRequest, SyncBatchRequest, TaskOfferRequest, TemporaryPasswordRequest,
    UnpackScanRequest, UnpackStartRequest,
)
from .security import authenticate_access, hash_password, issue_session, refresh_session, verify_password
from .seed import ensure_location, seed_bootstrap_users, seed_demo
from .services.allocation import AllocationError, allocate_order
from .services.inventory import InventoryError, move_inventory
from .services.picking import (
    PickError, accept_task, cancel_order, commit_pick, recover_stow, recovery_snapshot, short_pick, task_snapshot,
)
from .services.scheduling import active_task_for_actor, claim_next_task, reject_offer
from .services.operations import (
    OperationError, active_unpack, apply_cycle_count, boh_move, complete_unpack, damage_move, record_cycle_count,
    scan_unpack, start_cycle_count, start_unpack, unpack_summary,
)
from .services.sla import board_target_seconds, effective_elapsed_seconds
from .services.fulfillment import FulfillmentError, complete_delivery, handoff_task, stage_task, start_pack_rack
from .services.ops_platform import get_worker_state, update_device_telemetry
from .services.workforce import (
    MANAGER_ROLES, WorkforceError, add_pay_adjustment, create_employee, employee_payload,
    issue_temporary_password, payroll_preview, promote_employee, record_attendance, record_performance,
    request_password_reset, update_employee,
)
from .telemetry import emit as emit_telemetry, ping as telemetry_ping
from .ops_router import router as ops_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    migrate_schema()
    from .database import SessionLocal

    db = SessionLocal()
    try:
        with db.begin():
            seed_bootstrap_users(db)
            if os.getenv("DEMO_SEED", "0") == "1":
                seed_demo(db)
    finally:
        db.close()
    yield


class ApiPrefixMiddleware:
    """Normalize the public /api gateway prefix before FastAPI routing."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] in {"http", "websocket"}:
            path = scope.get("path", "")
            if path == "/api" or path.startswith("/api/"):
                normalized = path[4:] or "/"
                scope = dict(scope)
                scope["path"] = normalized
                raw_path = scope.get("raw_path")
                if raw_path:
                    scope["raw_path"] = normalized.encode("utf-8")
        await self.app(scope, receive, send)


app = FastAPI(title="FulfillOS", version="0.4.0", lifespan=lifespan)
app.add_middleware(ApiPrefixMiddleware)
app.include_router(ops_router)
# Router-level fallback for hosting layers that preserve the public /api prefix
# but adapt the ASGI app in a way that bypasses outer middleware path mutation.
app.mount("/api", app, name="api-prefix-alias")

DASHBOARD_DIR = Path(__file__).resolve().parents[2] / "dashboard"
if DASHBOARD_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(DASHBOARD_DIR)), name="static")


def actor(authorization: str | None = Header(None), db: Session = Depends(get_db)) -> tuple[User, Device]:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing bearer token")
    auth = authenticate_access(db, authorization[7:])
    if not auth:
        raise HTTPException(401, "Session expired or invalid")
    user, device = auth[0], auth[1]
    # End the read-only authentication transaction so command handlers can open
    # their explicit atomic transaction on the same request-scoped session.
    db.commit()
    return user, device


def manager_actor(who=Depends(actor)) -> tuple[User, Device]:
    user, device = who
    if user.role.upper() not in MANAGER_ROLES:
        raise HTTPException(403, "Supervisor or admin role required")
    return user, device


@app.get("/")
def root():
    return {"name": "FulfillOS", "version": "0.4.0", "dashboard": "/dashboard"}


@app.get("/health")
def health():
    database_status = "unavailable"
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        database_status = "connected"
    except Exception:
        database_status = "unavailable"

    telemetry_status = "connected" if telemetry_ping() else "disabled_or_unavailable"
    return {
        "ok": database_status == "connected",
        "version": "0.4.0",
        "database": database_status,
        "telemetry": telemetry_status,
        "server_time": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/dashboard")
def dashboard_file():
    path = DASHBOARD_DIR / "index.html"
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path)


@app.post("/auth/login")
def login(req: LoginRequest, db: Session = Depends(get_db)):
    with db.begin():
        user = db.scalar(select(User).where(User.username == req.username))
        if not user or not user.active or not verify_password(req.password, user.password_hash):
            raise HTTPException(401, "Invalid credentials")
        device = db.get(Device, req.device_id)
        if device is None:
            device = Device(id=req.device_id, trusted=True, app_version=req.app_version)
            db.add(device)
            db.flush()
        if not device.trusted:
            raise HTTPException(403, "Device is not trusted")
        device.app_version = req.app_version or device.app_version
        access, refresh, _ = issue_session(db, user, device)
        return {
            "access_token": access,
            "refresh_token": refresh,
            "user_id": user.id,
            "username": user.username,
            "role": user.role,
            "device_id": device.id,
        }


@app.post("/auth/refresh")
def refresh(req: RefreshRequest, db: Session = Depends(get_db)):
    with db.begin():
        result = refresh_session(db, req.refresh_token, req.device_id)
        if not result:
            raise HTTPException(401, "Refresh rejected")
        access, refresh_token, record = result
        user = db.get(User, record.user_id)
        return {
            "access_token": access,
            "refresh_token": refresh_token,
            "user_id": user.id,
            "username": user.username,
            "role": user.role,
            "device_id": record.device_id,
        }


@app.post("/auth/forgot-password", status_code=202)
def forgot_password(req: ForgotPasswordRequest, db: Session = Depends(get_db)):
    # Deliberately generic: never reveal whether a username/email exists.
    with db.begin():
        request_password_reset(db, req.identifier)
    return {"accepted": True, "message": "If the account exists, a supervisor can issue a temporary password."}


@app.post("/auth/change-password")
def change_password(req: ChangePasswordRequest, who=Depends(actor), db: Session = Depends(get_db)):
    user, _ = who
    with db.begin():
        user = db.get(User, user.id)
        if not user or not verify_password(req.current_password, user.password_hash):
            raise HTTPException(400, "Current password is incorrect")
        if req.current_password == req.new_password:
            raise HTTPException(400, "New password must be different")
        user.password_hash = hash_password(req.new_password)
        sessions = db.scalars(select(SessionToken).where(SessionToken.user_id == user.id)).all()
        for session in sessions:
            session.revoked = True
    return {"changed": True, "reauthentication_required": True}


@app.post("/devices/heartbeat")
def heartbeat(req: HeartbeatRequest, who=Depends(actor), db: Session = Depends(get_db)):
    user, device = who
    with db.begin():
        now = datetime.now(timezone.utc)
        device = db.get(Device, device.id)
        device.last_seen_at = now
        device.last_user_id = user.id
        device.status = req.connectivity.strip().upper()
        device.app_version = req.app_version or device.app_version
        update_device_telemetry(
            db,
            device.id,
            battery_percent=req.battery_percent,
            connectivity=device.status,
            last_location_id=req.last_location_id,
        )
        active = active_task_for_actor(db, user.id, device.id)
        current_task_id = active.id if active else None
        worker_state = get_worker_state(db, user.id, create=True)
        worker_state_name = worker_state.state if worker_state else "OFFLINE"
    mismatch = bool(req.current_task_id and req.current_task_id != current_task_id)
    emit_telemetry(
        "device_health",
        {
            "device_id": device.id,
            "actor_id": user.id,
            "status": device.status,
            "app_version": device.app_version,
            "current_task_id": current_task_id,
            "client_reported_task_id": req.current_task_id,
            "task_mismatch": mismatch,
            "worker_state": worker_state_name,
            "activity": req.activity,
            "battery_percent": req.battery_percent,
            "last_location_id": req.last_location_id,
            "observed_at": datetime.now(timezone.utc),
        },
    )
    return {
        "ok": True,
        "server_time": datetime.now(timezone.utc).isoformat(),
        "current_task_id": current_task_id,
        "client_reported_task_id": req.current_task_id,
        "task_mismatch": mismatch,
        "worker_state": worker_state_name,
    }


@app.get("/me")
def me(who=Depends(actor)):
    user, device = who
    return {
        "user_id": user.id, "username": user.username, "role": user.role,
        "device_id": device.id, "device_status": device.status, "trusted": device.trusted,
    }


@app.get("/me/active-task")
def my_active_task(who=Depends(actor), db: Session = Depends(get_db)):
    user, device = who
    task = active_task_for_actor(db, user.id, device.id)
    return {"task": task_snapshot(db, task) if task else None}


@app.post("/tasks/claim-next")
def claim_next(who=Depends(actor), db: Session = Depends(get_db)):
    user, device = who
    with db.begin():
        task = claim_next_task(db, user.id, device.id)
        return {"task": task}


@app.get("/locations/parse/{location_id:path}")
def parse_loc(location_id: str):
    try:
        p = parse_location(location_id)
        return p.__dict__
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/inventory/product/{asin}")
def inventory_by_product(asin: str, db: Session = Depends(get_db)):
    product = db.scalar(select(Product).where(Product.asin == asin))
    if not product:
        raise HTTPException(404, "Product not found")
    balances = db.scalars(select(InventoryBalance).where(InventoryBalance.product_id == product.id)).all()
    return {
        "product": {"id": product.id, "asin": product.asin, "title": product.title},
        "total_on_hand": sum(b.qty_on_hand for b in balances),
        "locations": [
            {"location_id": b.location_id, "qty_on_hand": b.qty_on_hand, "qty_reserved": b.qty_reserved, "version": b.version}
            for b in balances
        ],
    }


@app.get("/inventory/location/{location_id:path}")
def inventory_by_location(location_id: str, db: Session = Depends(get_db)):
    loc = db.get(Location, location_id)
    if not loc:
        raise HTTPException(404, "Location not found")
    balances = db.scalars(select(InventoryBalance).where(InventoryBalance.location_id == location_id)).all()
    items = []
    for b in balances:
        product = db.get(Product, b.product_id)
        items.append({"product_id": b.product_id, "asin": product.asin if product else None, "title": product.title if product else None, "qty": b.qty_on_hand})
    return {"location_id": location_id, "items": items}


@app.get("/inventory/barcode/{barcode}")
def inventory_by_barcode(barcode: str, db: Session = Depends(get_db)):
    mapping = db.scalar(select(Barcode).where(Barcode.code == barcode))
    if not mapping:
        raise HTTPException(404, "Barcode not mapped")
    product = db.get(Product, mapping.product_id)
    balances = db.scalars(select(InventoryBalance).where(InventoryBalance.product_id == mapping.product_id)).all()
    return {
        "barcode": barcode,
        "product": {
            "id": product.id,
            "asin": product.asin,
            "title": product.title,
            "temperature_class": product.temperature_class,
            "handling_class": product.handling_class,
        },
        "total_on_hand": sum(b.qty_on_hand for b in balances),
        "locations": [
            {
                "location_id": b.location_id,
                "qty_on_hand": b.qty_on_hand,
                "qty_reserved": b.qty_reserved,
                "version": b.version,
            }
            for b in balances
        ],
    }


@app.post("/inventory/move")
def inventory_move(req: InventoryMoveRequest, who=Depends(actor), db: Session = Depends(get_db)):
    user, device = who
    try:
        with db.begin():
            result = move_inventory(
                db, event_id=req.event_id, product_id=req.product_id, qty=req.qty,
                source_location_id=req.source_location_id, destination_location_id=req.destination_location_id,
                reason=req.reason, order_id=req.order_id, task_id=req.task_id,
                user_id=user.id, device_id=device.id,
            )
            return {"duplicate": result.duplicate, "movement_id": result.movement.id, "source_qty": result.source_qty, "destination_qty": result.destination_qty}
    except InventoryError as e:
        raise HTTPException(409, str(e))


@app.post("/inventory/receive")
def receive(req: ReceiveRequest, who=Depends(actor), db: Session = Depends(get_db)):
    user, device = who
    try:
        with db.begin():
            result = move_inventory(
                db, event_id=req.event_id, product_id=req.product_id, qty=req.qty,
                source_location_id=None, destination_location_id=req.destination_location_id,
                reason="RECEIVE", user_id=user.id, device_id=device.id,
            )
            return {"duplicate": result.duplicate, "movement_id": result.movement.id, "destination_qty": result.destination_qty}
    except InventoryError as e:
        raise HTTPException(409, str(e))


@app.post("/orders")
def create_order(req: OrderCreate, who=Depends(actor), db: Session = Depends(get_db)):
    with db.begin():
        order = Order(external_ref=req.external_ref, priority=req.priority)
        db.add(order)
        db.flush()
        for line in req.lines:
            product = db.get(Product, line.product_id)
            if not product:
                raise HTTPException(400, f"Unknown product {line.product_id}")
            # A fulfillment hold does not falsify physical inventory. It only
            # removes blocked stock from what can be promised to new orders.
            from .services.ops_platform import product_orderability
            availability = product_orderability(db, line.product_id)
            if (
                availability["blocked_stock"] > 0
                and availability["fulfillable_stock"] < line.qty
            ):
                raise HTTPException(
                    409,
                    {
                        "code": "FULFILLMENT_ZONE_DISABLED",
                        "message": "Requested quantity is temporarily unavailable for fulfillment",
                        "product_id": line.product_id,
                        "physical_stock": availability["physical_stock"],
                        "fulfillable_stock": availability["fulfillable_stock"],
                        "blocked_reasons": availability["blocked_reasons"],
                    },
                )
            db.add(OrderLine(order_id=order.id, product_id=line.product_id, requested_qty=line.qty))
        db.flush()
        return {"order_id": order.id, "status": order.status}


@app.post("/orders/{order_id}/allocate")
def allocate(order_id: str, who=Depends(actor), db: Session = Depends(get_db)):
    try:
        with db.begin():
            order = db.get(Order, order_id)
            if not order:
                raise HTTPException(404, "Order not found")
            task = allocate_order(db, order)
            snapshot = task_snapshot(db, task)
            # In live operation, clocked-in AVAILABLE workers have runtime-state
            # rows. When at least one exists, allocation immediately broadcasts
            # the order; clean test/bootstrap environments keep legacy READY flow.
            from .models_ops import WorkerRuntimeState
            from .services.ops_platform import broadcast_task
            available_workers = db.scalar(
                select(func.count()).select_from(WorkerRuntimeState).where(
                    WorkerRuntimeState.state == "AVAILABLE"
                )
            ) or 0
            if available_workers:
                dispatch = broadcast_task(db, task)
                snapshot = task_snapshot(db, task)
                snapshot["dispatch"] = dispatch
            return snapshot
    except AllocationError as e:
        raise HTTPException(409, str(e))


@app.post("/tasks/{task_id}/offer")
def offer(task_id: str, req: TaskOfferRequest, who=Depends(actor), db: Session = Depends(get_db)):
    with db.begin():
        task = db.get(PickTask, task_id)
        if not task:
            raise HTTPException(404, "Task not found")
        if task.status != TaskStatus.READY.value:
            raise HTTPException(409, "Task not ready")
        task.assigned_user_id = req.user_id
        task.assigned_device_id = req.device_id
        task.status = TaskStatus.OFFERED.value
        task.offered_at = datetime.now(timezone.utc)
        task.server_version += 1
        order = db.get(Order, task.order_id)
        order.status = OrderStatus.OFFERED.value
        return task_snapshot(db, task)


@app.post("/tasks/{task_id}/reject")
def reject(task_id: str, req: RejectOfferRequest, who=Depends(actor), db: Session = Depends(get_db)):
    user, device = who
    try:
        with db.begin():
            task = db.get(PickTask, task_id)
            if not task:
                raise HTTPException(404, "Task not found")
            return reject_offer(db, task, user.id, device.id, req.reason)
    except PickError as e:
        raise HTTPException(409, {"code": e.code, "message": str(e)})


@app.post("/tasks/{task_id}/accept")
def accept(task_id: str, who=Depends(actor), db: Session = Depends(get_db)):
    user, device = who
    try:
        with db.begin():
            task = db.get(PickTask, task_id)
            if not task:
                raise HTTPException(404, "Task not found")
            return accept_task(db, task, user.id, device.id)
    except PickError as e:
        raise HTTPException(409, {"code": e.code, "message": str(e)})


@app.get("/tasks/{task_id}")
def get_task(task_id: str, who=Depends(actor), db: Session = Depends(get_db)):
    task = db.get(PickTask, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    snap = task_snapshot(db, task)
    snap["sla"] = {
        "target_seconds": board_target_seconds(task.expected_units),
        "effective_elapsed_seconds": effective_elapsed_seconds(db, task),
    }
    return snap


@app.post("/tasks/{task_id}/scan")
def scan(task_id: str, req: PickScanRequest, who=Depends(actor), db: Session = Depends(get_db)):
    user, device = who
    try:
        with db.begin():
            task = db.get(PickTask, task_id)
            if not task:
                raise HTTPException(404, "Task not found")
            ack = commit_pick(
                db, task=task, event_id=req.event_id, client_seq=req.client_seq,
                task_item_id=req.task_item_id, location_id=req.location_id,
                product_id=req.product_id, qty=req.qty, barcode=req.barcode,
                user_id=user.id, device_id=device.id,
            )
            return {"duplicate": ack.duplicate, "snapshot": ack.snapshot}
    except PickError as e:
        task = db.get(PickTask, task_id)
        detail = {"code": e.code, "message": str(e), "authoritative_snapshot": task_snapshot(db, task) if task else None}
        raise HTTPException(409, detail)


@app.post("/tasks/{task_id}/short")
def short_task_item(task_id: str, req: ShortPickRequest, who=Depends(actor), db: Session = Depends(get_db)):
    user, device = who
    try:
        with db.begin():
            task = db.get(PickTask, task_id)
            if not task:
                raise HTTPException(404, "Task not found")
            ack = short_pick(
                db,
                task=task,
                event_id=req.event_id,
                client_seq=req.client_seq,
                task_item_id=req.task_item_id,
                qty=req.qty,
                reason=req.reason,
                user_id=user.id,
                device_id=device.id,
            )
            return {"duplicate": ack.duplicate, "snapshot": ack.snapshot}
    except PickError as e:
        task = db.get(PickTask, task_id)
        detail = {
            "code": e.code,
            "message": str(e),
            "authoritative_snapshot": task_snapshot(db, task) if task else None,
        }
        raise HTTPException(409, detail)


@app.post("/tasks/{task_id}/sync")
def sync(task_id: str, req: SyncBatchRequest, who=Depends(actor), db: Session = Depends(get_db)):
    user, device = who
    if req.task_id != task_id:
        raise HTTPException(400, "Task id mismatch")
    acks = []
    events = sorted(req.events, key=lambda e: e.client_seq)
    for event in events:
        p = event.payload
        try:
            with db.begin():
                task = db.get(PickTask, task_id)
                if not task:
                    raise PickError("Task not found", "TASK_NOT_FOUND")
                if event.event_type == "PICK":
                    ack = commit_pick(
                        db, task=task, event_id=event.event_id, client_seq=event.client_seq,
                        task_item_id=p["task_item_id"], location_id=p["location_id"],
                        product_id=p["product_id"], qty=int(p["qty"]), barcode=p.get("barcode"),
                        user_id=user.id, device_id=device.id,
                    )
                elif event.event_type == "SHORT":
                    ack = short_pick(
                        db, task=task, event_id=event.event_id, client_seq=event.client_seq,
                        task_item_id=p["task_item_id"], qty=int(p["qty"]),
                        reason=p.get("reason", "MISSING_AT_LOCATION"),
                        user_id=user.id, device_id=device.id,
                    )
                else:
                    acks.append({"event_id": event.event_id, "status": "REJECTED", "code": "UNSUPPORTED_EVENT"})
                    continue
                acks.append({
                    "event_id": event.event_id,
                    "status": "ACKED",
                    "duplicate": ack.duplicate,
                    "server_version": ack.snapshot["server_version"],
                })
        except (PickError, KeyError, ValueError) as e:
            code = e.code if isinstance(e, PickError) else "INVALID_EVENT_PAYLOAD"
            acks.append({"event_id": event.event_id, "status": "REJECTED", "code": code, "message": str(e)})
            break
    task = db.get(PickTask, task_id)
    return {"acks": acks, "authoritative_snapshot": task_snapshot(db, task) if task else None}


@app.post("/orders/{order_id}/cancel")
def cancel(order_id: str, req: CancelRequest, who=Depends(actor), db: Session = Depends(get_db)):
    with db.begin():
        order = db.get(Order, order_id)
        if not order:
            raise HTTPException(404, "Order not found")
        return cancel_order(db, order, req.reason)


@app.get("/tasks/{task_id}/recovery")
def task_recovery(task_id: str, who=Depends(actor), db: Session = Depends(get_db)):
    task = db.get(PickTask, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    try:
        return recovery_snapshot(db, task)
    except PickError as e:
        raise HTTPException(409, {"code": e.code, "message": str(e)})


@app.post("/tasks/{task_id}/recovery/stow")
def task_recovery_stow(task_id: str, req: RecoveryStowRequest, who=Depends(actor), db: Session = Depends(get_db)):
    user, device = who
    try:
        with db.begin():
            task = db.get(PickTask, task_id)
            if not task:
                raise HTTPException(404, "Task not found")
            return recover_stow(
                db,
                task=task,
                event_id=req.event_id,
                product_id=req.product_id,
                qty=req.qty,
                destination_location_id=req.destination_location_id,
                user_id=user.id,
                device_id=device.id,
            )
    except PickError as e:
        raise HTTPException(409, {"code": e.code, "message": str(e)})


@app.post("/tasks/{task_id}/downtime/start")
def downtime_start(task_id: str, req: DowntimeRequest, who=Depends(actor), db: Session = Depends(get_db)):
    with db.begin():
        if not db.get(PickTask, task_id):
            raise HTTPException(404, "Task not found")
        seg = DowntimeSegment(task_id=task_id, kind=req.kind, source=req.source, started_at=datetime.now(timezone.utc))
        db.add(seg)
        db.flush()
        return {"segment_id": seg.id, "started_at": seg.started_at}


@app.post("/tasks/{task_id}/downtime/{segment_id}/stop")
def downtime_stop(task_id: str, segment_id: str, who=Depends(actor), db: Session = Depends(get_db)):
    with db.begin():
        seg = db.get(DowntimeSegment, segment_id)
        if not seg or seg.task_id != task_id:
            raise HTTPException(404, "Segment not found")
        seg.ended_at = datetime.now(timezone.utc)
        return {"segment_id": seg.id, "ended_at": seg.ended_at}



@app.post("/tasks/{task_id}/pack-rack/start")
def pack_rack_start(task_id: str, who=Depends(actor), db: Session = Depends(get_db)):
    user, device = who
    try:
        with db.begin():
            task = db.get(PickTask, task_id)
            if not task:
                raise HTTPException(404, "Task not found")
            return start_pack_rack(db, task, user.id, device.id)
    except FulfillmentError as e:
        raise HTTPException(409, {"code": e.code, "message": str(e)})


@app.post("/tasks/{task_id}/stage")
def task_stage(task_id: str, req: StageRequest, who=Depends(actor), db: Session = Depends(get_db)):
    user, device = who
    try:
        with db.begin():
            task = db.get(PickTask, task_id)
            if not task:
                raise HTTPException(404, "Task not found")
            return stage_task(db, task, req.stage_location_id, user.id, device.id)
    except FulfillmentError as e:
        raise HTTPException(409, {"code": e.code, "message": str(e)})


@app.post("/tasks/{task_id}/handoff")
def task_handoff(task_id: str, req: HandoffRequest, who=Depends(actor), db: Session = Depends(get_db)):
    user, device = who
    try:
        with db.begin():
            task = db.get(PickTask, task_id)
            if not task:
                raise HTTPException(404, "Task not found")
            return handoff_task(db, task, req.handoff_ref, user.id, device.id)
    except FulfillmentError as e:
        raise HTTPException(409, {"code": e.code, "message": str(e)})


@app.post("/tasks/{task_id}/complete")
def task_complete(task_id: str, who=Depends(actor), db: Session = Depends(get_db)):
    user, device = who
    try:
        with db.begin():
            task = db.get(PickTask, task_id)
            if not task:
                raise HTTPException(404, "Task not found")
            return complete_delivery(db, task, user.id, device.id)
    except FulfillmentError as e:
        raise HTTPException(409, {"code": e.code, "message": str(e)})


@app.get("/unpack/active")
def unpack_active(temperature_class: str | None = None, who=Depends(actor), db: Session = Depends(get_db)):
    user, device = who
    session = active_unpack(db, user.id, device.id, temperature_class)
    return {"session": unpack_summary(db, session) if session else None}


@app.post("/unpack/sessions")
def unpack_start(req: UnpackStartRequest, who=Depends(actor), db: Session = Depends(get_db)):
    user, device = who
    try:
        with db.begin():
            session = start_unpack(db, req.temperature_class, user.id, device.id)
            return unpack_summary(db, session)
    except OperationError as e:
        raise HTTPException(409, {"code": e.code, "message": str(e)})


@app.post("/unpack/sessions/{session_id}/scan")
def unpack_scan(session_id: str, req: UnpackScanRequest, who=Depends(actor), db: Session = Depends(get_db)):
    try:
        with db.begin():
            session = db.get(UnpackSession, session_id)
            if not session:
                raise HTTPException(404, "Unpack session not found")
            return scan_unpack(db, session, req.event_id, req.product_id, req.qty)
    except OperationError as e:
        raise HTTPException(409, {"code": e.code, "message": str(e)})


@app.post("/unpack/sessions/{session_id}/complete")
def unpack_complete(session_id: str, who=Depends(actor), db: Session = Depends(get_db)):
    try:
        with db.begin():
            session = db.get(UnpackSession, session_id)
            if not session:
                raise HTTPException(404, "Unpack session not found")
            return complete_unpack(db, session)
    except OperationError as e:
        raise HTTPException(409, {"code": e.code, "message": str(e)})


@app.get("/unpack/sessions/{session_id}")
def unpack_get(session_id: str, who=Depends(actor), db: Session = Depends(get_db)):
    session = db.get(UnpackSession, session_id)
    if not session:
        raise HTTPException(404, "Unpack session not found")
    return unpack_summary(db, session)


@app.post("/boh/move")
def boh_move_endpoint(req: BOHMoveRequest, who=Depends(actor), db: Session = Depends(get_db)):
    user, device = who
    try:
        with db.begin():
            return boh_move(
                db, event_id=req.event_id, product_id=req.product_id, qty=req.qty,
                source_location_id=req.source_location_id, destination_location_id=req.destination_location_id,
                user_id=user.id, device_id=device.id,
            )
    except OperationError as e:
        raise HTTPException(409, {"code": e.code, "message": str(e)})


@app.post("/damage")
def damage_endpoint(req: DamageRequest, who=Depends(actor), db: Session = Depends(get_db)):
    user, device = who
    try:
        with db.begin():
            return damage_move(
                db, event_id=req.event_id, product_id=req.product_id, qty=req.qty,
                source_location_id=req.source_location_id, reason=req.reason,
                user_id=user.id, device_id=device.id,
            )
    except OperationError as e:
        raise HTTPException(409, {"code": e.code, "message": str(e)})


@app.post("/cycle-count/sessions")
def cycle_count_start(req: CycleCountStartRequest, who=Depends(actor), db: Session = Depends(get_db)):
    user, _ = who
    try:
        with db.begin():
            session = start_cycle_count(db, req.location_id, user.id)
            return {"session_id": session.id, "location_id": session.location_id, "status": session.status}
    except OperationError as e:
        raise HTTPException(409, {"code": e.code, "message": str(e)})


@app.post("/cycle-count/sessions/{session_id}/count")
def cycle_count_line(session_id: str, req: CycleCountLineRequest, who=Depends(actor), db: Session = Depends(get_db)):
    try:
        with db.begin():
            session = db.get(CycleCountSession, session_id)
            if not session:
                raise HTTPException(404, "Cycle count session not found")
            entry = record_cycle_count(db, session, req.product_id, req.counted_qty)
            return {
                "entry_id": entry.id, "product_id": entry.product_id, "system_qty": entry.system_qty,
                "counted_qty": entry.counted_qty, "variance": entry.variance,
            }
    except OperationError as e:
        raise HTTPException(409, {"code": e.code, "message": str(e)})


@app.post("/cycle-count/sessions/{session_id}/apply")
def cycle_count_apply(session_id: str, req: CycleCountApplyRequest, who=Depends(actor), db: Session = Depends(get_db)):
    user, device = who
    try:
        with db.begin():
            session = db.get(CycleCountSession, session_id)
            if not session:
                raise HTTPException(404, "Cycle count session not found")
            return apply_cycle_count(db, session, req.reason, user.id, device.id)
    except (OperationError, InventoryError) as e:
        code = e.code if isinstance(e, OperationError) else "INVENTORY_CONFLICT"
        raise HTTPException(409, {"code": code, "message": str(e)})


@app.get("/dashboard/summary")
def dashboard_summary(db: Session = Depends(get_db)):
    tasks = db.scalars(select(PickTask)).all()
    counts = {status.value: 0 for status in TaskStatus}
    for t in tasks:
        counts[t.status] = counts.get(t.status, 0) + 1
    active = []
    for t in tasks:
        if t.status in {TaskStatus.OFFERED.value, TaskStatus.ACCEPTED.value, TaskStatus.PICKING.value, TaskStatus.PICKED.value, TaskStatus.RECOVERY_REQUIRED.value}:
            snap = task_snapshot(db, t)
            snap["target_seconds"] = board_target_seconds(t.expected_units)
            snap["effective_elapsed_seconds"] = effective_elapsed_seconds(db, t)
            active.append(snap)
    return {
        "task_counts": counts,
        "devices_online": db.scalar(
            select(func.count()).select_from(Device).where(
                Device.status == "ONLINE",
                Device.last_seen_at >= datetime.now(timezone.utc) - timedelta(seconds=15),
            )
        ) or 0,
        "orders_recovery_required": db.scalar(select(func.count()).select_from(Order).where(Order.recovery_required == True)) or 0,  # noqa: E712
        "active_tasks": active,
    }


@app.get("/admin/employees")
def admin_employees(period: str | None = None, who=Depends(manager_actor), db: Session = Depends(get_db)):
    users = db.scalars(
        select(User)
        .join(EmployeeProfile, EmployeeProfile.user_id == User.id)
        .order_by(EmployeeProfile.full_name)
    ).all()
    return {"employees": [employee_payload(db, user, period=period) for user in users]}


@app.post("/admin/employees", status_code=201)
def admin_create_employee(req: EmployeeCreateRequest, who=Depends(manager_actor), db: Session = Depends(get_db)):
    manager, _ = who
    try:
        with db.begin():
            user, generated_password = create_employee(db, req)
            payload = employee_payload(db, user)
            payload["temporary_password"] = generated_password
            payload["created_by"] = manager.id
            return payload
    except WorkforceError as e:
        raise HTTPException(409, {"code": e.code, "message": str(e)})


@app.get("/admin/employees/{user_id}")
def admin_employee_detail(user_id: str, period: str | None = None, who=Depends(manager_actor), db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if not user or not db.get(EmployeeProfile, user_id):
        raise HTTPException(404, "Employee not found")
    return employee_payload(db, user, period=period)


@app.patch("/admin/employees/{user_id}")
def admin_update_employee(user_id: str, req: EmployeeUpdateRequest, who=Depends(manager_actor), db: Session = Depends(get_db)):
    try:
        with db.begin():
            user = db.get(User, user_id)
            if not user:
                raise HTTPException(404, "Employee not found")
            update_employee(db, user, req)
            return employee_payload(db, user)
    except WorkforceError as e:
        raise HTTPException(409, {"code": e.code, "message": str(e)})


@app.post("/admin/employees/{user_id}/promote")
def admin_promote_employee(
    user_id: str,
    req: PromotionRequest,
    who=Depends(manager_actor),
    db: Session = Depends(get_db),
):
    manager, _ = who
    try:
        with db.begin():
            user = db.get(User, user_id)
            if not user or not db.get(EmployeeProfile, user_id):
                raise HTTPException(404, "Employee not found")
            record = promote_employee(
                db,
                user=user,
                to_role=req.to_role,
                reason=req.reason,
                approver_id=manager.id,
                new_base_salary_cents=req.new_base_salary_cents,
                effective_at=req.effective_at,
            )
            return {
                "promotion_id": record.id,
                "user_id": user.id,
                "from_role": record.from_role,
                "to_role": record.to_role,
                "reason": record.reason,
                "old_base_salary_cents": record.old_base_salary_cents,
                "new_base_salary_cents": record.new_base_salary_cents,
                "effective_at": record.effective_at.isoformat(),
                "approved_by_user_id": record.approved_by_user_id,
                "employee": employee_payload(db, user),
            }
    except WorkforceError as e:
        raise HTTPException(409, {"code": e.code, "message": str(e)})


@app.post("/admin/employees/{user_id}/attendance", status_code=201)
def admin_add_attendance(user_id: str, req: AttendanceCreateRequest, who=Depends(manager_actor), db: Session = Depends(get_db)):
    manager, _ = who
    try:
        with db.begin():
            if not db.get(EmployeeProfile, user_id):
                raise HTTPException(404, "Employee not found")
            entry = record_attendance(db, user_id, req, manager.id)
            return {
                "id": entry.id,
                "late_minutes": entry.late_minutes,
                "overtime_minutes": entry.overtime_minutes,
                "status": entry.status,
            }
    except WorkforceError as e:
        raise HTTPException(409, {"code": e.code, "message": str(e)})


@app.post("/admin/employees/{user_id}/performance-events", status_code=201)
def admin_add_performance_event(user_id: str, req: PerformanceEventCreateRequest, who=Depends(manager_actor), db: Session = Depends(get_db)):
    with db.begin():
        if not db.get(EmployeeProfile, user_id):
            raise HTTPException(404, "Employee not found")
        event = record_performance(db, user_id, req)
        return {"id": event.id, "event_type": event.event_type, "occurred_at": event.occurred_at.isoformat()}


@app.post("/admin/employees/{user_id}/pay-adjustments", status_code=201)
def admin_add_pay_adjustment(user_id: str, req: PayAdjustmentCreateRequest, who=Depends(manager_actor), db: Session = Depends(get_db)):
    manager, _ = who
    with db.begin():
        if not db.get(EmployeeProfile, user_id):
            raise HTTPException(404, "Employee not found")
        item = add_pay_adjustment(db, user_id, req, manager.id)
        return {
            "id": item.id,
            "kind": item.kind,
            "amount_cents": item.amount_cents,
            "approved": item.approved,
        }


@app.get("/admin/employees/{user_id}/payroll-preview")
def admin_payroll_preview(user_id: str, period: str | None = None, who=Depends(manager_actor), db: Session = Depends(get_db)):
    try:
        if not db.get(EmployeeProfile, user_id):
            raise HTTPException(404, "Employee not found")
        return payroll_preview(db, user_id, period)
    except WorkforceError as e:
        raise HTTPException(400, {"code": e.code, "message": str(e)})


@app.get("/admin/password-resets")
def admin_password_resets(who=Depends(manager_actor), db: Session = Depends(get_db)):
    requests = db.scalars(
        select(PasswordResetRequest)
        .where(PasswordResetRequest.status == "PENDING")
        .order_by(PasswordResetRequest.requested_at.asc())
    ).all()
    payload = []
    for item in requests:
        user = db.get(User, item.user_id)
        profile = db.get(EmployeeProfile, item.user_id)
        payload.append({
            "id": item.id,
            "user_id": item.user_id,
            "username": user.username if user else None,
            "full_name": profile.full_name if profile else None,
            "requested_at": item.requested_at.isoformat(),
            "status": item.status,
        })
    return {"requests": payload}


@app.post("/admin/password-resets/{reset_id}/issue-temporary-password")
def admin_issue_temporary_password(reset_id: str, req: TemporaryPasswordRequest, who=Depends(manager_actor), db: Session = Depends(get_db)):
    manager, _ = who
    try:
        with db.begin():
            reset = db.get(PasswordResetRequest, reset_id)
            if not reset or reset.status != "PENDING":
                raise HTTPException(404, "Pending reset request not found")
            password = issue_temporary_password(db, reset, manager.id, req.password)
            return {
                "resolved": True,
                "temporary_password": password,
                "warning": "Shown once. Give it to the employee securely and ask them to change it after login.",
            }
    except WorkforceError as e:
        raise HTTPException(409, {"code": e.code, "message": str(e)})


@app.get("/v1/control-tower/summary")
def control_tower_compat_summary(db: Session = Depends(get_db)):
    """Compatibility/read-model endpoint for the Next.js supervisor control tower."""
    tasks = db.scalars(select(PickTask)).all()
    devices = db.scalars(select(Device)).all()

    task_counts: dict[str, int] = {}
    for task in tasks:
        state = "PACKING_RACKING" if task.status == TaskStatus.PACK_RACK.value else task.status
        task_counts[state] = task_counts.get(state, 0) + 1

    associate_states = {
        "WAITING": 0,
        "OFFERED": 0,
        "PICKING": 0,
        "PACKING_RACKING": 0,
        "BREAK": 0,
        "OTHER_ACTIVITY": 0,
        "OFFLINE": 0,
    }
    active_by_user: dict[str, str] = {}
    active_statuses = {
        TaskStatus.OFFERED.value,
        TaskStatus.ACCEPTED.value,
        TaskStatus.PICKING.value,
        TaskStatus.PICKED.value,
        TaskStatus.PACK_RACK.value,
        TaskStatus.STAGED.value,
        TaskStatus.HANDOFF_READY.value,
        TaskStatus.HANDED_OFF.value,
        TaskStatus.CANCEL_PENDING.value,
        TaskStatus.RECOVERY_REQUIRED.value,
    }
    for task in sorted(tasks, key=lambda item: item.updated_at or datetime.min.replace(tzinfo=timezone.utc)):
        if not task.assigned_user_id or task.status not in active_statuses:
            continue
        if task.status == TaskStatus.OFFERED.value:
            state = "OFFERED"
        elif task.status in {TaskStatus.ACCEPTED.value, TaskStatus.PICKING.value, TaskStatus.PICKED.value}:
            state = "PICKING"
        elif task.status == TaskStatus.PACK_RACK.value:
            state = "PACKING_RACKING"
        else:
            state = "OTHER_ACTIVITY"
        active_by_user[task.assigned_user_id] = state

    for state in active_by_user.values():
        associate_states[state] += 1

    device_state_by_user: dict[str, str] = {}
    live_cutoff = datetime.now(timezone.utc) - timedelta(seconds=15)
    for device in devices:
        if not device.last_user_id:
            continue
        last_seen = device.last_seen_at
        if last_seen and last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=timezone.utc)
        fresh_online = (
            device.status == "ONLINE"
            and last_seen is not None
            and last_seen >= live_cutoff
        )
        current = device_state_by_user.get(device.last_user_id)
        if current != "ONLINE":
            device_state_by_user[device.last_user_id] = "ONLINE" if fresh_online else "OFFLINE"

    for user_id, device_state in device_state_by_user.items():
        if user_id in active_by_user:
            continue
        associate_states["WAITING" if device_state == "ONLINE" else "OFFLINE"] += 1

    recovery_required = []
    for task in tasks:
        if task.status != TaskStatus.RECOVERY_REQUIRED.value:
            continue
        order = db.get(Order, task.order_id)
        recovery_required.append({
            "taskId": task.id,
            "orderId": task.order_id,
            "associateId": task.assigned_user_id,
            "reason": order.cancellation_reason if order else None,
            "version": task.server_version,
        })

    return {
        "associates": associate_states,
        "tasks": task_counts,
        "recoveryRequired": recovery_required,
    }


@app.websocket("/ws/dashboard")
async def dashboard_ws(ws: WebSocket):
    await ws.accept()
    try:
        while True:
            await ws.send_json({"type": "heartbeat", "server_time": datetime.now(timezone.utc).isoformat()})
            await ws.receive_text()
    except WebSocketDisconnect:
        return
