from __future__ import annotations

import json
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    AuditLog, CycleCountEntry, CycleCountSession, InventoryBalance, Location, Product,
    UnpackEntry, UnpackSession,
)
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


def start_unpack(db: Session, temperature_class: str, user_id: str, device_id: str) -> UnpackSession:
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
        return existing

    session = UnpackSession(temperature_class=temp, tote_location_id=tote, user_id=user_id, device_id=device_id)
    db.add(session)
    db.flush()
    try:
        set_worker_state(db, user_id, "UNPACKING", activity_ref=session.id, reason="UNPACK_STARTED")
    except OpsError as exc:
        raise OperationError(str(exc), exc.code) from exc
    audit(db, "UNPACK_STARTED", "UNPACK_SESSION", session.id, user_id=user_id, device_id=device_id, payload={"tote": tote, "temperature": temp})
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
    return {
        "session_id": session.id,
        "status": session.status,
        "temperature_class": session.temperature_class,
        "tote_location_id": session.tote_location_id,
        "items": recommendations,
    }


def complete_unpack(db: Session, session: UnpackSession) -> dict:
    if session.status != "OPEN":
        return unpack_summary(db, session)
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
