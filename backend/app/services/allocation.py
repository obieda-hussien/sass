from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import InventoryBalance, Location, Order, OrderLine, OrderStatus, PickTask, PickTaskItem, Product, TaskStatus
from .ops_platform import candidate_inventory_sort_key, is_location_fulfillable, route_sort_key as ops_route_sort_key
from .ops_optimization import optimize_task_route


class AllocationError(Exception):
    pass


def location_sort_key(loc: Location) -> tuple:
    # Deterministic route baseline. A real optimizer can replace this with a graph/travel-cost engine.
    return (
        loc.temperature_class == "FROZEN",   # frozen later by default
        loc.temperature_class == "CHILLED",  # chilled near the end
        loc.aisle or 9999,
        loc.level or "Z",
        loc.slot or 9999,
        loc.id,
    )


def allocate_order(db: Session, order: Order) -> PickTask:
    if order.status not in {OrderStatus.CREATED.value, OrderStatus.ALLOCATED.value}:
        raise AllocationError(f"Order cannot be allocated from {order.status}")

    lines = db.scalars(select(OrderLine).where(OrderLine.order_id == order.id)).all()
    planned: list[tuple[OrderLine, InventoryBalance, Location, int]] = []
    for line in lines:
        remaining = line.requested_qty
        product = db.get(Product, line.product_id)
        if not product:
            raise AllocationError("Missing product")
        balances = db.scalars(select(InventoryBalance).where(InventoryBalance.product_id == line.product_id)).all()
        candidates: list[tuple[InventoryBalance, Location]] = []
        for bal in balances:
            loc = db.get(Location, bal.location_id)
            if not loc or not loc.active or not loc.pickable or not loc.sellable:
                continue
            if not is_location_fulfillable(db, product, loc):
                continue
            available = bal.qty_on_hand - bal.qty_reserved
            if available <= 0:
                continue
            if loc.temperature_class != product.temperature_class:
                # Ambient products may be allowed in ambient-only here; site rules can be richer later.
                continue
            if product.handling_class in {"HAZ", "HRV"} and loc.handling_class != product.handling_class:
                continue
            candidates.append((bal, loc))
        # FEFO decides which stock to reserve; the final task sequence is then
        # independently optimized so the picker does not bounce warm/cold/warm.
        candidates.sort(key=lambda pair: candidate_inventory_sort_key(db, product, pair[1]))

        for bal, loc in candidates:
            available = bal.qty_on_hand - bal.qty_reserved
            take = min(remaining, available)
            if take <= 0:
                continue
            planned.append((line, bal, loc, take))
            remaining -= take
            if remaining == 0:
                break
        if remaining:
            raise AllocationError(f"Insufficient sellable inventory for product {line.product_id}; shortage={remaining}")

    task = PickTask(order_id=order.id, status=TaskStatus.READY.value, expected_units=sum(p[3] for p in planned))
    db.add(task)
    db.flush()

    sequence = 1
    for line, bal, loc, qty in sorted(planned, key=lambda p: ops_route_sort_key(p[2])):
        bal.qty_reserved += qty
        bal.version += 1
        line.allocated_qty += qty
        db.add(PickTaskItem(
            task_id=task.id,
            order_line_id=line.id,
            product_id=line.product_id,
            source_location_id=loc.id,
            planned_qty=qty,
            picked_qty=0,
            sequence=sequence,
        ))
        sequence += 1
    order.status = OrderStatus.ALLOCATED.value
    db.flush()
    optimize_task_route(db, task, persist=True)
    db.flush()
    return task
