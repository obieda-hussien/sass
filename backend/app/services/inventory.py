from __future__ import annotations

from dataclasses import dataclass
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import InventoryBalance, InventoryMovement, Location, Product


class InventoryError(Exception):
    pass


@dataclass
class MoveResult:
    movement: InventoryMovement
    duplicate: bool
    source_qty: int | None
    destination_qty: int | None


def get_balance(db: Session, location_id: str, product_id: str) -> InventoryBalance | None:
    return db.scalar(select(InventoryBalance).where(
        InventoryBalance.location_id == location_id,
        InventoryBalance.product_id == product_id,
    ))


def ensure_balance(db: Session, location_id: str, product_id: str) -> InventoryBalance:
    bal = get_balance(db, location_id, product_id)
    if bal is None:
        bal = InventoryBalance(location_id=location_id, product_id=product_id, qty_on_hand=0, qty_reserved=0)
        db.add(bal)
        db.flush()
    return bal


def move_inventory(
    db: Session,
    *,
    event_id: str,
    product_id: str,
    qty: int,
    source_location_id: str | None,
    destination_location_id: str | None,
    reason: str,
    order_id: str | None = None,
    task_id: str | None = None,
    user_id: str | None = None,
    device_id: str | None = None,
    consume_reserved: bool = False,
) -> MoveResult:
    existing = db.scalar(select(InventoryMovement).where(InventoryMovement.event_id == event_id))
    if existing:
        src = get_balance(db, existing.source_location_id, product_id) if existing.source_location_id else None
        dst = get_balance(db, existing.destination_location_id, product_id) if existing.destination_location_id else None
        return MoveResult(existing, True, src.qty_on_hand if src else None, dst.qty_on_hand if dst else None)

    if qty <= 0:
        raise InventoryError("Quantity must be positive")
    if db.get(Product, product_id) is None:
        raise InventoryError("Unknown product")
    if source_location_id and db.get(Location, source_location_id) is None:
        raise InventoryError(f"Unknown source location {source_location_id}")
    if destination_location_id and db.get(Location, destination_location_id) is None:
        raise InventoryError(f"Unknown destination location {destination_location_id}")
    if source_location_id == destination_location_id:
        raise InventoryError("Source and destination cannot be identical")

    src = None
    dst = None
    if source_location_id:
        src = ensure_balance(db, source_location_id, product_id)
        if consume_reserved:
            if src.qty_on_hand < qty:
                raise InventoryError(f"Insufficient on-hand inventory: {src.qty_on_hand} < {qty}")
            if src.qty_reserved < qty:
                raise InventoryError(f"Reserved inventory conflict: {src.qty_reserved} < {qty}")
            src.qty_reserved -= qty
        else:
            available = src.qty_on_hand - src.qty_reserved
            if available < qty:
                raise InventoryError(f"Insufficient available inventory: {available} < {qty}")
        src.qty_on_hand -= qty
        src.version += 1

    if destination_location_id:
        dst = ensure_balance(db, destination_location_id, product_id)
        dst.qty_on_hand += qty
        dst.version += 1

    movement = InventoryMovement(
        event_id=event_id,
        product_id=product_id,
        qty=qty,
        source_location_id=source_location_id,
        destination_location_id=destination_location_id,
        reason=reason,
        order_id=order_id,
        task_id=task_id,
        user_id=user_id,
        device_id=device_id,
    )
    db.add(movement)
    db.flush()
    return MoveResult(movement, False, src.qty_on_hand if src else None, dst.qty_on_hand if dst else None)
