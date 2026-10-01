from __future__ import annotations

import json
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    AuditLog, CycleCountEntry, CycleCountSession, InventoryBalance, Location, Order, OrderLine, Product,
    UnpackEntry, UnpackManifestLine, UnpackSession,
)
from ..models_ops import OrderBag
from .compatibility import storage_compatible
from .inventory import InventoryError, get_balance, move_inventory
from .ops_platform import OpsError, set_worker_state


class OperationError(Exception):
    def __init__(self, message: str, code: str = "OPERATION_ERROR"):
        super().__init__(message)
        self.code = code


UNPACK_TOTES = {
    "AMBIENT": "TSCRET001",
    "CHILLED": "TSCRETCHL01",
    "FROZEN": "TSCRETFRZ01",
}


def audit(db: Session, event_type: str, entity_type: str, entity_id: str, *, user_id: str | None = None,
          device_id: str | None = None, payload: dict | None = None) -> None:
    db.add(AuditLog(
        event_type=event_type, entity_type=entity_type, entity_id=entity_id,
        user_id=user_id, device_id=device_id,
        payload_json=json.dumps(payload or {}, separators=(",", ":")),
    ))


def start_unpack(
    db: Session,
    temperature_class: str,
    user_id: str,
    device_id: str,
    *,
    source_ref: str | None = None,
    expected_items: list[dict] | None = None,
) -> UnpackSession:
    temp = temperature_class.upper()
    tote = UNPACK_TOTES.get(temp)
    if not tote:
        raise OperationError("Unsupported temperature class", "BAD_TEMPERATURE_CLASS")
    if not db.get(Location, tote):
        raise OperationError(f"Unpack tote {tote} is not configured", "TOTE_NOT_CONFIGURED")

    # Retry/resume invariant: a PDA may reboot or the network may time out after
    # creating a session. Reissuing "start" must return the same open session
    # instead of creating duplicate workflow state.
    existing = db.scalar(
        select(UnpackSession)
        .where(
            UnpackSession.temperature_class == temp,
            UnpackSession.user_id == user_id,
            UnpackSession.device_id == device_id,
            UnpackSession.status == "OPEN",
        )
        .order_by(UnpackSession.created_at.desc())
    )
    if existing:
        if expected_items and not existing.manifest_locked:
            set_unpack_manifest(db, existing, expected_items, source_ref=source_ref or "EXPLICIT")
        elif source_ref and not existing.manifest_locked:
            bind_unpack_source(db, existing, source_ref)
        return existing

    session = UnpackSession(
        temperature_class=temp,
        tote_location_id=tote,
        user_id=user_id,
        device_id=device_id,
    )
    db.add(session)
    db.flush()
    try:
        set_worker_state(db, user_id, "UNPACKING", activity_ref=session.id, reason="UNPACK_STARTED")
    except OpsError as exc:
        raise OperationError(str(exc), exc.code) from exc
    audit(db, "UNPACK_STARTED", "UNPACK_SESSION", session.id, user_id=user_id, device_id=device_id, payload={"tote": tote, "temperature": temp})
    if expected_items:
        set_unpack_manifest(db, session, expected_items, source_ref=source_ref or "EXPLICIT")
    elif source_ref:
        bind_unpack_source(db, session, source_ref)
    return session


def set_unpack_manifest(
    db: Session,
    session: UnpackSession,
    expected_items: list[dict],
    *,
    source_ref: str,
) -> UnpackSession:
    if session.status != "OPEN":
        raise OperationError("Unpack session is closed", "SESSION_CLOSED")
    if session.manifest_locked:
        if (session.source_ref or "") == source_ref.strip():
            return session
        raise OperationError("Unpack manifest is already locked to another source", "MANIFEST_ALREADY_BOUND")
    existing_scan = db.scalar(select(UnpackEntry.id).where(UnpackEntry.session_id == session.id).limit(1))
    if existing_scan is not None:
        raise OperationError("Bind the expected manifest before scanning items", "MANIFEST_BIND_TOO_LATE")

    grouped: dict[str, int] = {}
    for item in expected_items:
        product_id = str(item["product_id"])
        qty = int(item["expected_qty"])
        if qty <= 0:
            raise OperationError("Expected quantities must be positive", "BAD_EXPECTED_QTY")
        product = db.get(Product, product_id)
        if product is None:
            raise OperationError(f"Unknown manifest product {product_id}", "PRODUCT_NOT_FOUND")
        if product.temperature_class != session.temperature_class:
            raise OperationError(
                f"{product.title} is {product.temperature_class}, not {session.temperature_class}",
                "TEMPERATURE_MISMATCH",
            )
        grouped[product_id] = grouped.get(product_id, 0) + qty

    if not grouped:
        raise OperationError("Expected manifest cannot be empty", "EMPTY_MANIFEST")

    for product_id, qty in grouped.items():
        db.add(UnpackManifestLine(session_id=session.id, product_id=product_id, expected_qty=qty))
    session.source_ref = source_ref.strip()
    session.expected_units = sum(grouped.values())
    session.manifest_locked = True
    db.flush()
    audit(
        db,
        "UNPACK_MANIFEST_BOUND",
        "UNPACK_SESSION",
        session.id,
        user_id=session.user_id,
        device_id=session.device_id,
        payload={"source_ref": session.source_ref, "expected_units": session.expected_units},
    )
    return session


def bind_unpack_source(db: Session, session: UnpackSession, source_ref: str) -> UnpackSession:
    ref = source_ref.strip()
    if not ref:
        raise OperationError("Source reference is required", "SOURCE_REQUIRED")

    order: Order | None = None
    if ref.upper().startswith("ORDER:"):
        key = ref.split(":", 1)[1].strip()
        order = db.get(Order, key)
        if order is None:
            order = db.scalar(select(Order).where(Order.external_ref == key))
    else:
        bag = db.scalar(select(OrderBag).where(OrderBag.spoo_code == ref))
        if bag is None:
            bag = db.scalar(select(OrderBag).where(OrderBag.spoo_code == ref.upper()))
        if bag is not None:
            order = db.get(Order, bag.order_id)

    if order is None:
        raise OperationError("No trusted manifest found for this bag/order reference", "UNPACK_SOURCE_NOT_FOUND")

    # A SPOO identifies the order, not the contents of one physical bag. One
    # scan loads all picked units for this temperature; every other SPOO of the
    # same order must resolve to the same workflow and cannot be unpacked twice.
    previous = db.scalar(select(UnpackSession).where(
        UnpackSession.source_order_id == order.id,
        UnpackSession.temperature_class == session.temperature_class,
        UnpackSession.id != session.id,
    ))
    if previous:
        raise OperationError(
            "This order is already being unpacked or has been completed",
            "ORDER_ALREADY_UNPACKED",
        )
    if session.manifest_locked:
        if session.source_order_id == order.id:
            return session
        raise OperationError("Unpack manifest is already locked to another order", "MANIFEST_ALREADY_BOUND")

    lines = db.scalars(select(OrderLine).where(OrderLine.order_id == order.id)).all()
    expected: list[dict] = []
    for line in lines:
        product = db.get(Product, line.product_id)
        if product is None or product.temperature_class != session.temperature_class:
            continue
        qty = max(0, int(line.picked_qty))
        if qty > 0:
            expected.append({"product_id": line.product_id, "expected_qty": qty})
    if not expected:
        raise OperationError(
            "The source has no picked items for this temperature class",
            "EMPTY_MANIFEST",
        )
    set_unpack_manifest(db, session, expected, source_ref=f"ORDER:{order.id}")
    session.source_order_id = order.id
    db.flush()
    return session


def active_unpack(db: Session, user_id: str, device_id: str, temperature_class: str | None = None) -> UnpackSession | None:
    query = (
        select(UnpackSession)
        .where(
            UnpackSession.user_id == user_id,
            UnpackSession.device_id == device_id,
            UnpackSession.status == "OPEN",
        )
        .order_by(UnpackSession.created_at.desc())
    )
    if temperature_class:
        query = query.where(UnpackSession.temperature_class == temperature_class.upper())
    return db.scalar(query)


def scan_unpack(db: Session, session: UnpackSession, event_id: str, product_id: str, qty: int) -> dict:
    existing = db.scalar(select(UnpackEntry).where(UnpackEntry.event_id == event_id))
    if existing:
        return {"duplicate": True, "entry_id": existing.id, "tote_location_id": session.tote_location_id}
    if session.status != "OPEN":
        raise OperationError("Unpack session is not open", "SESSION_CLOSED")
    if not session.manifest_locked:
        raise OperationError("Scan the bag/source manifest before unpacking items", "UNPACK_MANIFEST_REQUIRED")
    manifest_line = db.scalar(
        select(UnpackManifestLine).where(
            UnpackManifestLine.session_id == session.id,
            UnpackManifestLine.product_id == product_id,
        )
    )
    if manifest_line is None:
        raise OperationError("Scanned item is not expected in this bag/manifest", "UNEXPECTED_UNPACK_ITEM")
    verified_before = sum(
        row.qty
        for row in db.scalars(
            select(UnpackEntry).where(
                UnpackEntry.session_id == session.id,
                UnpackEntry.product_id == product_id,
            )
        ).all()
    )
    if verified_before + qty > manifest_line.expected_qty:
        raise OperationError(
            f"Scan would exceed expected quantity {manifest_line.expected_qty}",
            "UNPACK_OVERAGE",
        )
    product = db.get(Product, product_id)
    if not product:
        raise OperationError("Unknown product", "PRODUCT_NOT_FOUND")
    if product.temperature_class != session.temperature_class:
        raise OperationError(
            f"Product requires {product.temperature_class}, session is {session.temperature_class}",
            "TEMPERATURE_MISMATCH",
        )
    move_inventory(
        db, event_id=f"unpack-move:{event_id}", product_id=product_id, qty=qty,
        source_location_id=None, destination_location_id=session.tote_location_id,
        reason="UNPACK_RECEIVE", user_id=session.user_id, device_id=session.device_id,
    )
    entry = UnpackEntry(session_id=session.id, event_id=event_id, product_id=product_id, qty=qty)
    db.add(entry)
    db.flush()
    audit(db, "UNPACK_ITEM", "UNPACK_SESSION", session.id, user_id=session.user_id, device_id=session.device_id,
          payload={"product_id": product_id, "qty": qty, "event_id": event_id})
    return {"duplicate": False, "entry_id": entry.id, "tote_location_id": session.tote_location_id}


def unpack_summary(db: Session, session: UnpackSession) -> dict:
    entries = db.scalars(select(UnpackEntry).where(UnpackEntry.session_id == session.id)).all()
    grouped: dict[str, int] = {}
    for e in entries:
        grouped[e.product_id] = grouped.get(e.product_id, 0) + e.qty
    recommendations = []
    for product_id, qty in grouped.items():
        product = db.get(Product, product_id)
        locations = db.scalars(select(Location).where(Location.logical == False, Location.stowable == True)).all()  # noqa: E712
        compatible = [loc.id for loc in locations if storage_compatible(product, loc)[0]]
        recommendations.append({"product_id": product_id, "qty": qty, "compatible_destinations": compatible[:10]})
    manifest_rows = db.scalars(
        select(UnpackManifestLine).where(UnpackManifestLine.session_id == session.id)
    ).all()
    manifest = []
    verified_units = 0
    for row in manifest_rows:
        verified = grouped.get(row.product_id, 0)
        verified_units += verified
        product = db.get(Product, row.product_id)
        manifest.append({
            "product_id": row.product_id,
            "asin": product.asin if product else None,
            "title": product.title if product else "Unknown product",
            "expected_qty": row.expected_qty,
            "verified_qty": verified,
            "missing_qty": max(0, row.expected_qty - verified),
        })
    remaining_units = max(0, session.expected_units - verified_units)
    return {
        "session_id": session.id,
        "status": session.status,
        "temperature_class": session.temperature_class,
        "tote_location_id": session.tote_location_id,
        "source_ref": session.source_ref,
        "manifest_locked": bool(session.manifest_locked),
        "expected_units": int(session.expected_units),
        "verified_units": verified_units,
        "remaining_units": remaining_units,
        "complete_ready": bool(session.manifest_locked and session.expected_units > 0 and remaining_units == 0),
        "manifest": manifest,
        "items": recommendations,
    }


def complete_unpack(db: Session, session: UnpackSession) -> dict:
    if session.status != "OPEN":
        return unpack_summary(db, session)
    summary = unpack_summary(db, session)
    if not session.manifest_locked:
        raise OperationError("A trusted expected manifest is required before completion", "UNPACK_MANIFEST_REQUIRED")
    if not summary["complete_ready"]:
        missing = [
            f'{row["title"]} x{row["missing_qty"]}'
            for row in summary["manifest"]
            if row["missing_qty"] > 0
        ]
        raise OperationError(
            "Unpack is incomplete. Missing: " + ", ".join(missing[:8]),
            "UNPACK_INCOMPLETE",
        )
    session.status = "COMPLETED"
    session.completed_at = datetime.now(timezone.utc)
    try:
        set_worker_state(db, session.user_id, "AVAILABLE", reason="UNPACK_COMPLETED", force=True)
    except OpsError as exc:
        raise OperationError(str(exc), exc.code) from exc
    audit(db, "UNPACK_COMPLETED", "UNPACK_SESSION", session.id, user_id=session.user_id, device_id=session.device_id)
    db.flush()
    return unpack_summary(db, session)


def boh_move(db: Session, *, event_id: str, product_id: str, qty: int, source_location_id: str,
             destination_location_id: str, user_id: str, device_id: str) -> dict:
    product = db.get(Product, product_id)
    dest = db.get(Location, destination_location_id)
    if not product or not dest:
        raise OperationError("Unknown product or destination", "NOT_FOUND")
    compatible, code = storage_compatible(product, dest)
    if not compatible:
        raise OperationError(f"Destination is incompatible: {code}", code or "INCOMPATIBLE")
    try:
        result = move_inventory(
            db, event_id=event_id, product_id=product_id, qty=qty,
            source_location_id=source_location_id, destination_location_id=destination_location_id,
            reason="BOH_MOVE", user_id=user_id, device_id=device_id,
        )
    except InventoryError as e:
        raise OperationError(str(e), "INVENTORY_CONFLICT") from e
    audit(db, "BOH_MOVE", "PRODUCT", product_id, user_id=user_id, device_id=device_id,
          payload={"source": source_location_id, "destination": destination_location_id, "qty": qty, "event_id": event_id})
    return {"duplicate": result.duplicate, "source_qty": result.source_qty, "destination_qty": result.destination_qty}


def damage_move(db: Session, *, event_id: str, product_id: str, qty: int, source_location_id: str,
                reason: str, user_id: str, device_id: str) -> dict:
    try:
        result = move_inventory(
            db, event_id=event_id, product_id=product_id, qty=qty,
            source_location_id=source_location_id, destination_location_id="DMG",
            reason=f"DAMAGE:{reason[:64]}", user_id=user_id, device_id=device_id,
        )
    except InventoryError as e:
        raise OperationError(str(e), "INVENTORY_CONFLICT") from e
    audit(db, "DAMAGE_MOVE", "PRODUCT", product_id, user_id=user_id, device_id=device_id,
          payload={"source": source_location_id, "qty": qty, "reason": reason, "event_id": event_id})
    return {"duplicate": result.duplicate, "damage_qty": result.destination_qty}


def start_cycle_count(db: Session, location_id: str, user_id: str) -> CycleCountSession:
    loc = db.get(Location, location_id)
    if not loc:
        raise OperationError("Unknown location", "LOCATION_NOT_FOUND")
    session = CycleCountSession(location_id=location_id, user_id=user_id)
    db.add(session)
    db.flush()
    try:
        set_worker_state(db, user_id, "CYCLE_COUNT", activity_ref=session.id, reason="CYCLE_COUNT_STARTED")
    except OpsError as exc:
        raise OperationError(str(exc), exc.code) from exc
    audit(db, "CYCLE_COUNT_STARTED", "CYCLE_COUNT", session.id, user_id=user_id, payload={"location": location_id})
    return session


def record_cycle_count(db: Session, session: CycleCountSession, product_id: str, counted_qty: int) -> CycleCountEntry:
    if session.status != "OPEN":
        raise OperationError("Cycle count is closed", "SESSION_CLOSED")
    if not db.get(Product, product_id):
        raise OperationError("Unknown product", "PRODUCT_NOT_FOUND")
    bal = get_balance(db, session.location_id, product_id)
    system_qty = bal.qty_on_hand if bal else 0
    entry = db.scalar(select(CycleCountEntry).where(
        CycleCountEntry.session_id == session.id, CycleCountEntry.product_id == product_id,
    ))
    if entry is None:
        entry = CycleCountEntry(
            session_id=session.id, product_id=product_id, system_qty=system_qty,
            counted_qty=counted_qty, variance=counted_qty - system_qty,
        )
        db.add(entry)
    else:
        entry.system_qty = system_qty
        entry.counted_qty = counted_qty
        entry.variance = counted_qty - system_qty
    db.flush()
    return entry


def apply_cycle_count(db: Session, session: CycleCountSession, reason: str, user_id: str, device_id: str) -> dict:
    if session.status != "OPEN":
        raise OperationError("Cycle count is closed", "SESSION_CLOSED")
    entries = db.scalars(select(CycleCountEntry).where(CycleCountEntry.session_id == session.id)).all()
    changes = []
    for entry in entries:
        if entry.applied or entry.variance == 0:
            continue
        if entry.variance > 0:
            result = move_inventory(
                db, event_id=f"cycle:{session.id}:{entry.product_id}", product_id=entry.product_id, qty=entry.variance,
                source_location_id=None, destination_location_id=session.location_id,
                reason=reason, user_id=user_id, device_id=device_id,
            )
        else:
            result = move_inventory(
                db, event_id=f"cycle:{session.id}:{entry.product_id}", product_id=entry.product_id, qty=-entry.variance,
                source_location_id=session.location_id, destination_location_id=None,
                reason=reason, user_id=user_id, device_id=device_id,
            )
        entry.applied = True
        changes.append({"product_id": entry.product_id, "variance": entry.variance, "movement_id": result.movement.id})
    session.status = "COMPLETED"
    session.completed_at = datetime.now(timezone.utc)
    try:
        set_worker_state(db, user_id, "AVAILABLE", reason="CYCLE_COUNT_COMPLETED", force=True)
    except OpsError as exc:
        raise OperationError(str(exc), exc.code) from exc
    audit(db, "CYCLE_COUNT_APPLIED", "CYCLE_COUNT", session.id, user_id=user_id, device_id=device_id, payload={"changes": changes})
    db.flush()
    return {"session_id": session.id, "status": session.status, "changes": changes}
