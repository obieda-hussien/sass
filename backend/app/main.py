from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from .config import get_settings
from .database import create_schema, get_db
from .models import (
    Associate,
    Barcode,
    DowntimeEvent,
    InventoryBalance,
    Product,
    ScanEvent,
    Task,
)
from .schemas import (
    AcceptTaskRequest,
    CancelTaskRequest,
    CountRequest,
    DamageRequest,
    DowntimeRequest,
    HandoffRequest,
    HeartbeatRequest,
    InventoryAdjustRequest,
    LocationCreate,
    MoveRequest,
    OfferRequest,
    OrderCreate,
    ProductCreate,
    ReconcileRequest,
    ScanPickRequest,
    ShortPickRequest,
    StageRequest,
    UnpackRequest,
)
from .serializers import inventory_balance_dict, task_dict
from .services import (
    accept_task,
    adjust_inventory,
    cancel_task,
    commit_pick_scan,
    commit_short_pick,
    control_tower_summary,
    create_order_and_task,
    create_product,
    ensure_location,
    find_location,
    find_product,
    get_or_create_balance,
    handoff_task,
    load_task,
    move_inventory,
    offer_next_task,
    stage_task,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    create_schema()
    yield


app = FastAPI(
    title="FulfillOS Execution API",
    version="0.2.0",
    lifespan=lifespan,
)
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "fulfillos-api", "version": "0.2.0"}


@app.post("/v1/catalog/products")
def post_product(request: ProductCreate, db: Session = Depends(get_db)) -> dict:
    with db.begin():
        product = create_product(db, **request.model_dump())
    return {"id": product.id, "sku": product.sku}


@app.post("/v1/locations")
def post_location(request: LocationCreate, db: Session = Depends(get_db)) -> dict:
    with db.begin():
        location = ensure_location(db, **request.model_dump())
    return {
        "id": location.id,
        "code": location.code,
        "temperatureClass": location.temperature_class,
        "handlingClass": location.handling_class,
    }


@app.get("/v1/inventory/location/{code}")
def inventory_by_location(code: str, db: Session = Depends(get_db)) -> dict:
    location = find_location(db, code)
    balances = db.scalars(
        select(InventoryBalance)
        .where(InventoryBalance.location_id == location.id)
        .options(
            joinedload(InventoryBalance.product),
            joinedload(InventoryBalance.location),
        )
        .order_by(InventoryBalance.on_hand.desc())
    ).all()
    return {"location": location.code, "inventory": [inventory_balance_dict(x) for x in balances]}


@app.get("/v1/inventory/item/{identifier}")
def inventory_by_item(identifier: str, db: Session = Depends(get_db)) -> dict:
    product = db.scalar(select(Product).where(Product.sku == identifier))
    if not product:
        barcode = db.get(Barcode, identifier)
        if barcode:
            product = db.get(Product, barcode.product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    balances = db.scalars(
        select(InventoryBalance)
        .where(InventoryBalance.product_id == product.id)
        .options(
            joinedload(InventoryBalance.product),
            joinedload(InventoryBalance.location),
        )
        .order_by(InventoryBalance.on_hand.desc())
    ).all()
    return {
        "product": {"sku": product.sku, "title": product.title},
        "totalOnHand": sum(x.on_hand for x in balances),
        "totalReserved": sum(x.reserved for x in balances),
        "locations": [inventory_balance_dict(x) for x in balances],
    }


@app.post("/v1/inventory/adjust")
def inventory_adjust(request: InventoryAdjustRequest, db: Session = Depends(get_db)) -> dict:
    with db.begin():
        balance = adjust_inventory(db, **request.model_dump())
    db.refresh(balance)
    return {"status": "COMMITTED", "balance": inventory_balance_dict(balance)}


@app.post("/v1/moves/boh")
def boh_move(request: MoveRequest, db: Session = Depends(get_db)) -> dict:
    with db.begin():
        result = move_inventory(
            db,
            event_id=request.event_id,
            product_sku=request.product_sku,
            source_code=request.source_location,
            destination_code=request.destination_location,
            quantity=request.quantity,
            reason=request.reason,
            actor_id=request.actor_id,
            device_id=request.device_id,
        )
    return result


@app.post("/v1/unpack")
def unpack(request: UnpackRequest, db: Session = Depends(get_db)) -> dict:
    destination_by_temperature = {
        "AMBIENT": "TSCRET001",
        "CHILLED": "TSCRETCHL01",
        "FROZEN": "TSCRETFRZ01",
    }
    destination = destination_by_temperature.get(request.temperature_class.upper())
    if not destination:
        raise HTTPException(status_code=422, detail="Unsupported temperature class")

    with db.begin():
        ensure_location(db, destination, pickable=False, stowable=True)
        balance = adjust_inventory(
            db,
            event_id=request.event_id,
            product_sku=request.product_sku,
            location_code=destination,
            delta=request.quantity,
            reason="UNPACK_RECEIPT",
            actor_id=request.actor_id,
            device_id=request.device_id,
        )
    return {"status": "COMMITTED", "unpackLocation": destination, "balanceId": balance.id}


@app.post("/v1/damage")
def damage(request: DamageRequest, db: Session = Depends(get_db)) -> dict:
    with db.begin():
        ensure_location(
            db,
            "DMG",
            handling_class_override="DAMAGE",
            pickable=False,
            stowable=True,
        )
        result = move_inventory(
            db,
            event_id=request.event_id,
            product_sku=request.product_sku,
            source_code=request.source_location,
            destination_code="DMG",
            quantity=request.quantity,
            reason=f"DAMAGE:{request.reason}",
            actor_id=request.actor_id,
            device_id=request.device_id,
        )
    return result


@app.post("/v1/count")
def cycle_count(request: CountRequest, db: Session = Depends(get_db)) -> dict:
    with db.begin():
        product = find_product(db, request.product_sku)
        location = find_location(db, request.location_code)
        balance = get_or_create_balance(
            db, product_id=product.id, location_id=location.id, lock=True
        )
        delta = request.counted_quantity - balance.on_hand
        if delta:
            balance = adjust_inventory(
                db,
                event_id=request.event_id,
                product_sku=request.product_sku,
                location_code=request.location_code,
                delta=delta,
                reason="CYCLE_COUNT_RECONCILIATION",
                actor_id=request.actor_id,
                device_id=request.device_id,
            )
    return {"status": "COMMITTED", "variance": delta, "onHand": balance.on_hand}


@app.post("/v1/orders")
def create_order(request: OrderCreate, db: Session = Depends(get_db)) -> dict:
    try:
        with db.begin():
            task = create_order_and_task(db, request)
    except Exception:
        db.rollback()
        raise
    return task_dict(task)


@app.post("/v1/tasks/offer")
def offer_task(request: OfferRequest, db: Session = Depends(get_db)) -> dict | None:
    with db.begin():
        task = offer_next_task(db, request.associate_id)
    return task_dict(task) if task else None


@app.post("/v1/tasks/{task_id}/accept")
def post_accept(
    task_id: str, request: AcceptTaskRequest, db: Session = Depends(get_db)
) -> dict:
    with db.begin():
        task = accept_task(
            db,
            task_id,
            associate_id=request.associate_id,
            device_id=request.device_id,
        )
    return task_dict(task)


@app.get("/v1/tasks/{task_id}")
def get_task(task_id: str, db: Session = Depends(get_db)) -> dict:
    return task_dict(load_task(db, task_id))


@app.post("/v1/tasks/{task_id}/scan")
def post_scan(
    task_id: str, request: ScanPickRequest, db: Session = Depends(get_db)
) -> dict:
    with db.begin():
        return commit_pick_scan(db, task_id, request)


@app.post("/v1/tasks/{task_id}/short")
def post_short(
    task_id: str, request: ShortPickRequest, db: Session = Depends(get_db)
) -> dict:
    with db.begin():
        return commit_short_pick(db, task_id, request)


@app.post("/v1/tasks/{task_id}/cancel")
def post_cancel(
    task_id: str, request: CancelTaskRequest, db: Session = Depends(get_db)
) -> dict:
    with db.begin():
        task = cancel_task(db, task_id, reason=request.reason, actor_id=request.actor_id)
    return task_dict(task)


@app.post("/v1/tasks/{task_id}/stage")
def post_stage(
    task_id: str, request: StageRequest, db: Session = Depends(get_db)
) -> dict:
    with db.begin():
        task = stage_task(
            db,
            task_id,
            location_code=request.location_code,
            associate_id=request.associate_id,
            device_id=request.device_id,
        )
    return task_dict(task)


@app.post("/v1/tasks/{task_id}/handoff")
def post_handoff(
    task_id: str, request: HandoffRequest, db: Session = Depends(get_db)
) -> dict:
    with db.begin():
        task = handoff_task(
            db,
            task_id,
            associate_id=request.associate_id,
            device_id=request.device_id,
            rider_ref=request.rider_ref,
        )
    return task_dict(task)


@app.post("/v1/devices/heartbeat")
def heartbeat(request: HeartbeatRequest, db: Session = Depends(get_db)) -> dict:
    with db.begin():
        associate = db.get(Associate, request.associate_id)
        if not associate:
            associate = Associate(
                id=request.associate_id,
                display_name=request.associate_id,
                state="WAITING",
            )
            db.add(associate)
        associate.updated_at = datetime.now(timezone.utc)
        if request.active_task_id:
            associate.active_task_id = request.active_task_id
    return {"status": "ok", "serverTime": datetime.now(timezone.utc)}


@app.post("/v1/downtime")
def downtime(request: DowntimeRequest, db: Session = Depends(get_db)) -> dict:
    with db.begin():
        if request.ended:
            event = db.scalar(
                select(DowntimeEvent).where(DowntimeEvent.id == request.event_id)
            )
            if not event:
                raise HTTPException(status_code=404, detail="Downtime event not found")
            event.ended_at = datetime.now(timezone.utc)
        else:
            event = DowntimeEvent(
                id=request.event_id,
                kind=request.kind,
                task_id=request.task_id,
                associate_id=request.associate_id,
                device_id=request.device_id,
                detail=request.detail,
            )
            db.add(event)
    return {"status": "ok", "eventId": request.event_id}


@app.post("/v1/sync/reconcile")
def reconcile(request: ReconcileRequest, db: Session = Depends(get_db)) -> dict:
    task = None
    if request.task_id:
        task = load_task(db, request.task_id)
    elif request.associate_id:
        task = db.scalar(
            select(Task)
            .where(
                Task.associate_id == request.associate_id,
                Task.state.in_(
                    [
                        "OFFERED",
                        "PICKING",
                        "PACKING_RACKING",
                        "STAGED",
                        "RECOVERY_REQUIRED",
                    ]
                ),
            )
            .order_by(Task.accepted_at.desc())
        )
        if task:
            task = load_task(db, task.id)

    committed_ids = set(
        db.scalars(
            select(ScanEvent.event_id).where(
                ScanEvent.event_id.in_(request.pending_event_ids or ["__none__"])
            )
        ).all()
    )

    return {
        "task": task_dict(task) if task else None,
        "serverVersion": task.version if task else None,
        "committedEventIds": sorted(committed_ids),
        "unknownEventIds": [
            event_id
            for event_id in request.pending_event_ids
            if event_id not in committed_ids
        ],
        "action": "RESUME" if task else "WAIT_FOR_TASK",
    }


@app.get("/v1/control-tower/summary")
def control_tower(db: Session = Depends(get_db)) -> dict:
    return control_tower_summary(db)


# Vercel's Python runtime imports this module-level ASGI app.
