from __future__ import annotations

import heapq
import json
import math
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..models import (
    CycleCountSession,
    InventoryBalance,
    Location,
    OrderLine,
    PickTask,
    PickTaskItem,
    Product,
    ScanEvent,
    TaskStatus,
    User,
)
from ..models_ops import (
    ActivePickLease,
    DeviceTelemetry,
    FulfillmentGuardRule,
    FulfillmentHold,
    InventoryAlert,
    InventoryLot,
    LocationOperationalProfile,
    OperationalIncident,
    ShiftSession,
    StowTask,
    TaskHandover,
    WarehouseEdge,
    WarehouseNode,
    WorkerDispatchProfile,
    WorkerQualification,
    WorkerRuntimeState,
)


DOMAIN_ORDER = {
    "AMBIENT": 0,
    "PRODUCE": 0,
    "HAZ": 0,
    "HRV": 0,
    "CHILLED": 1,
    "FROZEN": 2,
}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def location_domain(location: Location) -> str:
    if location.handling_class in {"HAZ", "HRV"}:
        return location.handling_class
    if location.fixture_type == "V":
        return "PRODUCE"
    return location.temperature_class or "AMBIENT"


def task_domains(db: Session, task: PickTask) -> set[str]:
    domains: set[str] = set()
    items = db.scalars(
        select(PickTaskItem).where(
            PickTaskItem.task_id == task.id,
            PickTaskItem.picked_qty < PickTaskItem.planned_qty,
        )
    ).all()
    for item in items:
        location = db.get(Location, item.source_location_id)
        if location:
            domains.add(location_domain(location))
    return domains


def worker_domain_reasons(db: Session, user_id: str, task: PickTask | None) -> list[str]:
    if task is None:
        return []
    profile = db.get(WorkerDispatchProfile, user_id)
    if profile is None:
        return []
    try:
        allowed = {str(value).upper() for value in json.loads(profile.allowed_domains_json or "[]")}
    except (TypeError, ValueError, json.JSONDecodeError):
        allowed = set()
    if not allowed:
        return []
    missing = sorted(task_domains(db, task) - allowed)
    return [f"DOMAIN_NOT_ALLOWED_{domain}" for domain in missing]


def set_worker_dispatch_profile(
    db: Session,
    *,
    user_id: str,
    home_domain: str | None,
    allowed_domains: list[str],
    manager_id: str,
) -> WorkerDispatchProfile:
    row = db.get(WorkerDispatchProfile, user_id)
    if row is None:
        row = WorkerDispatchProfile(user_id=user_id)
        db.add(row)
    row.home_domain = home_domain.strip().upper() if home_domain else None
    row.allowed_domains_json = json.dumps(sorted({d.strip().upper() for d in allowed_domains}), separators=(",", ":"))
    row.updated_by_user_id = manager_id
    row.updated_at = now_utc()
    db.flush()
    return row


def set_location_operational_profile(
    db: Session,
    *,
    location_id: str,
    node_id: str | None = None,
    capacity_units: int | None = None,
    average_pick_seconds: float | None = None,
    route_sequence_override: int | None = None,
) -> LocationOperationalProfile:
    if db.get(Location, location_id) is None:
        raise ValueError("Location not found")
    if node_id and db.get(WarehouseNode, node_id) is None:
        raise ValueError("Warehouse node not found")
    row = db.get(LocationOperationalProfile, location_id)
    if row is None:
        row = LocationOperationalProfile(location_id=location_id)
        db.add(row)
    if node_id is not None:
        row.node_id = node_id
    if capacity_units is not None:
        row.capacity_units = max(0, capacity_units)
    if average_pick_seconds is not None:
        row.average_pick_seconds = max(0.1, average_pick_seconds)
    if route_sequence_override is not None:
        row.route_sequence_override = route_sequence_override
    row.updated_at = now_utc()
    db.flush()
    return row


def location_capacity_snapshot(db: Session, location_id: str) -> dict[str, Any]:
    profile = db.get(LocationOperationalProfile, location_id)
    used = db.scalar(
        select(func.coalesce(func.sum(InventoryBalance.qty_on_hand), 0)).where(
            InventoryBalance.location_id == location_id
        )
    ) or 0
    capacity = profile.capacity_units if profile else None
    return {
        "location_id": location_id,
        "capacity_units": capacity,
        "used_units": int(used),
        "remaining_units": None if capacity is None else max(0, capacity - int(used)),
        "utilization_pct": None if not capacity else round((int(used) / capacity) * 100, 2),
    }


def destination_has_capacity(db: Session, location_id: str, incoming_qty: int) -> bool:
    snap = location_capacity_snapshot(db, location_id)
    remaining = snap["remaining_units"]
    return remaining is None or remaining >= incoming_qty


def create_warehouse_node(
    db: Session,
    *,
    node_id: str,
    site_id: str,
    name: str,
    node_type: str = "PICK",
    domain: str | None = None,
    aisle: int | None = None,
    x_m: float | None = None,
    y_m: float | None = None,
) -> WarehouseNode:
    row = db.get(WarehouseNode, node_id)
    if row is None:
        row = WarehouseNode(id=node_id)
        db.add(row)
    row.site_id = site_id
    row.name = name
    row.node_type = node_type
    row.domain = domain.strip().upper() if domain else None
    row.aisle = aisle
    row.x_m = x_m
    row.y_m = y_m
    row.active = True
    db.flush()
    return row


def upsert_warehouse_edge(
    db: Session,
    *,
    site_id: str,
    from_node_id: str,
    to_node_id: str,
    distance_m: float,
    one_way: bool = False,
    congestion_factor: float = 1.0,
) -> WarehouseEdge:
    if db.get(WarehouseNode, from_node_id) is None or db.get(WarehouseNode, to_node_id) is None:
        raise ValueError("Both warehouse nodes must exist")
    row = db.scalar(
        select(WarehouseEdge).where(
            WarehouseEdge.site_id == site_id,
            WarehouseEdge.from_node_id == from_node_id,
            WarehouseEdge.to_node_id == to_node_id,
        )
    )
    if row is None:
        row = WarehouseEdge(
            site_id=site_id,
            from_node_id=from_node_id,
            to_node_id=to_node_id,
        )
        db.add(row)
    row.distance_m = max(0.1, distance_m)
    row.one_way = one_way
    row.congestion_factor = max(0.1, congestion_factor)
    row.active = True
    db.flush()
    return row


def _live_aisle_load(db: Session, site_id: str) -> dict[int, int]:
    rows = db.execute(
        select(DeviceTelemetry.last_location_id, WorkerRuntimeState.state)
        .join(User, User.id == WorkerRuntimeState.user_id)
        .join(
            DeviceTelemetry,
            DeviceTelemetry.device_id.in_(
                select(__import__("app.models", fromlist=["Device"]).Device.id).where(
                    __import__("app.models", fromlist=["Device"]).Device.last_user_id == User.id
                )
            ),
            isouter=True,
        )
        .where(WorkerRuntimeState.state.not_in(["OFFLINE", "BREAK"]))
    ).all()
    loads: dict[int, int] = defaultdict(int)
    for location_id, _ in rows:
        if not location_id:
            continue
        location = db.get(Location, location_id)
        if location and location.site_id == site_id and location.aisle is not None:
            loads[location.aisle] += 1
    return dict(loads)


def _node_for_location(db: Session, location_id: str) -> WarehouseNode | None:
    profile = db.get(LocationOperationalProfile, location_id)
    if profile and profile.node_id:
        return db.get(WarehouseNode, profile.node_id)
    return None


def _adjacency(db: Session, site_id: str, aisle_load: dict[int, int] | None = None) -> dict[str, list[tuple[str, float]]]:
    aisle_load = aisle_load or {}
    nodes = {
        row.id: row
        for row in db.scalars(
            select(WarehouseNode).where(WarehouseNode.site_id == site_id, WarehouseNode.active == True)  # noqa: E712
        ).all()
    }
    graph: dict[str, list[tuple[str, float]]] = defaultdict(list)
    edges = db.scalars(
        select(WarehouseEdge).where(WarehouseEdge.site_id == site_id, WarehouseEdge.active == True)  # noqa: E712
    ).all()
    for edge in edges:
        target = nodes.get(edge.to_node_id)
        congestion = 1.0
        if target and target.aisle is not None:
            congestion += max(0, aisle_load.get(target.aisle, 0) - 1) * 0.06
        cost = float(edge.distance_m) * float(edge.congestion_factor) * congestion
        graph[edge.from_node_id].append((edge.to_node_id, cost))
        if not edge.one_way:
            graph[edge.to_node_id].append((edge.from_node_id, cost))
    return graph


def _dijkstra(graph: dict[str, list[tuple[str, float]]], start: str, goal: str) -> float | None:
    if start == goal:
        return 0.0
    queue: list[tuple[float, str]] = [(0.0, start)]
    seen: dict[str, float] = {}
    while queue:
        distance, node = heapq.heappop(queue)
        if node in seen:
            continue
        seen[node] = distance
        if node == goal:
            return distance
        for nxt, cost in graph.get(node, []):
            if nxt not in seen:
                heapq.heappush(queue, (distance + cost, nxt))
    return None


def heuristic_distance(a: Location, b: Location) -> float:
    if a.id == b.id:
        return 0.0
    if a.aisle is None or b.aisle is None:
        return 12.0
    aisle_cost = abs(a.aisle - b.aisle) * 7.5
    slot_cost = abs((a.slot or 0) - (b.slot or 0)) * 0.35
    floor_cost = 0.0 if a.floor == b.floor else 30.0
    domain_cost = 0.0 if location_domain(a) == location_domain(b) else 12.0
    return max(1.0, aisle_cost + slot_cost + floor_cost + domain_cost)


def shortest_location_distance(
    db: Session,
    from_location_id: str | None,
    to_location_id: str,
    *,
    congestion_aware: bool = True,
) -> float:
    target = db.get(Location, to_location_id)
    if target is None:
        return 999_999.0
    if not from_location_id:
        return 0.0
    source = db.get(Location, from_location_id)
    if source is None:
        return 999_999.0

    source_node = _node_for_location(db, source.id)
    target_node = _node_for_location(db, target.id)
    if source_node and target_node and source_node.site_id == target_node.site_id:
        load = _live_aisle_load(db, source.site_id) if congestion_aware else {}
        graph = _adjacency(db, source.site_id, load)
        graph_distance = _dijkstra(graph, source_node.id, target_node.id)
        if graph_distance is not None:
            return round(graph_distance, 2)

    distance = heuristic_distance(source, target)
    if congestion_aware and target.aisle is not None:
        live = _live_aisle_load(db, target.site_id).get(target.aisle, 0)
        distance *= 1.0 + max(0, live - 1) * 0.06
    return round(distance, 2)


def optimize_task_route(
    db: Session,
    task: PickTask,
    *,
    current_location_id: str | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    items = db.scalars(
        select(PickTaskItem).where(
            PickTaskItem.task_id == task.id,
            PickTaskItem.picked_qty < PickTaskItem.planned_qty,
        )
    ).all()
    if not items:
        return {
            "task_id": task.id,
            "route": [],
            "estimated_distance_m": 0.0,
            "estimated_seconds": 0,
            "backtracking_risk": 0,
        }

    enriched: list[tuple[PickTaskItem, Location]] = []
    for item in items:
        loc = db.get(Location, item.source_location_id)
        if loc:
            enriched.append((item, loc))

    route: list[tuple[PickTaskItem, Location, float]] = []
    cursor = current_location_id
    total_distance = 0.0
    for domain_rank in sorted({DOMAIN_ORDER.get(location_domain(loc), 0) for _, loc in enriched}):
        remaining = [
            pair for pair in enriched
            if DOMAIN_ORDER.get(location_domain(pair[1]), 0) == domain_rank
            and pair[0].id not in {x[0].id for x in route}
        ]
        while remaining:
            candidates = []
            for item, loc in remaining:
                profile = db.get(LocationOperationalProfile, loc.id)
                if profile and profile.route_sequence_override is not None and cursor is None:
                    distance = max(0.0, float(profile.route_sequence_override))
                else:
                    distance = shortest_location_distance(db, cursor, loc.id)
                candidates.append((distance, loc.aisle or 9999, loc.slot or 9999, item, loc))
            candidates.sort(key=lambda x: (x[0], x[1], x[2]))
            distance, _, _, item, loc = candidates[0]
            route.append((item, loc, distance))
            total_distance += max(0.0, distance)
            cursor = loc.id
            remaining = [pair for pair in remaining if pair[0].id != item.id]

    estimated_seconds = 0.0
    previous_aisle: int | None = None
    backtracking_risk = 0
    response_route = []
    for index, (item, loc, distance) in enumerate(route, start=1):
        profile = db.get(LocationOperationalProfile, loc.id)
        pick_seconds = profile.average_pick_seconds if profile else 12.0
        units = max(1, item.planned_qty - item.picked_qty)
        estimated_seconds += distance / 1.2 + pick_seconds * units
        if previous_aisle is not None and loc.aisle is not None:
            if DOMAIN_ORDER.get(location_domain(loc), 0) == 0 and loc.aisle < previous_aisle:
                backtracking_risk += 1
        previous_aisle = loc.aisle if loc.aisle is not None else previous_aisle
        if persist:
            item.sequence = index
        response_route.append({
            "task_item_id": item.id,
            "product_id": item.product_id,
            "location_id": loc.id,
            "domain": location_domain(loc),
            "aisle": loc.aisle,
            "sequence": index,
            "remaining_qty": item.planned_qty - item.picked_qty,
            "distance_from_previous_m": round(distance, 2),
        })

    if persist:
        task.server_version += 1
        db.flush()
    return {
        "task_id": task.id,
        "route": response_route,
        "estimated_distance_m": round(total_distance, 2),
        "estimated_seconds": int(math.ceil(estimated_seconds)),
        "backtracking_risk": backtracking_risk,
        "congestion_aware": True,
        "cold_chain_order": ["AMBIENT/PRODUCE/HAZ/HRV", "CHILLED", "FROZEN"],
    }


def distance_to_task_first_item(db: Session, task: PickTask, user_id: str) -> float | None:
    first = db.scalar(
        select(PickTaskItem)
        .where(
            PickTaskItem.task_id == task.id,
            PickTaskItem.picked_qty < PickTaskItem.planned_qty,
        )
        .order_by(PickTaskItem.sequence)
        .limit(1)
    )
    if first is None:
        return 0.0
    from ..models import Device

    device = db.scalar(
        select(Device).where(Device.last_user_id == user_id).order_by(Device.last_seen_at.desc()).limit(1)
    )
    telemetry = db.get(DeviceTelemetry, device.id) if device else None
    return shortest_location_distance(db, telemetry.last_location_id if telemetry else None, first.source_location_id)


def warehouse_heatmap(
    db: Session,
    *,
    from_at: datetime,
    to_at: datetime,
    site_id: str = "DEMO",
) -> list[dict[str, Any]]:
    stats: dict[str, dict[str, Any]] = {}
    events = db.scalars(
        select(ScanEvent).where(
            ScanEvent.created_at >= from_at,
            ScanEvent.created_at <= to_at,
            ScanEvent.event_type.in_(["PICK", "SHORT", "SKIP", "DAMAGED"]),
        )
    ).all()
    for event in events:
        try:
            payload = json.loads(event.payload_json or "{}")
        except json.JSONDecodeError:
            payload = {}
        location_id = payload.get("location_id")
        if not location_id and payload.get("task_item_id"):
            item = db.get(PickTaskItem, payload["task_item_id"])
            location_id = item.source_location_id if item else None
        location = db.get(Location, location_id) if location_id else None
        if not location or location.site_id != site_id:
            continue
        key = f"{location_domain(location)}:{location.aisle if location.aisle is not None else 'NA'}"
        row = stats.setdefault(key, {
            "key": key,
            "domain": location_domain(location),
            "aisle": location.aisle,
            "pick_events": 0,
            "short_events": 0,
            "damaged_events": 0,
            "skip_events": 0,
            "active_workers": 0,
        })
        if event.event_type == "PICK":
            row["pick_events"] += 1
        elif event.event_type == "SHORT":
            row["short_events"] += 1
        elif event.event_type == "DAMAGED":
            row["damaged_events"] += 1
        elif event.event_type == "SKIP":
            row["skip_events"] += 1

    from ..models import Device
    telemetry_rows = db.execute(
        select(DeviceTelemetry, Device)
        .join(Device, Device.id == DeviceTelemetry.device_id)
        .where(DeviceTelemetry.last_location_id.is_not(None))
    ).all()
    for telemetry, device in telemetry_rows:
        location = db.get(Location, telemetry.last_location_id)
        if not location or location.site_id != site_id or location.aisle is None:
            continue
        state = db.get(WorkerRuntimeState, device.last_user_id) if device.last_user_id else None
        if state is None or state.state in {"OFFLINE", "BREAK"}:
            continue
        key = f"{location_domain(location)}:{location.aisle}"
        row = stats.setdefault(key, {
            "key": key,
            "domain": location_domain(location),
            "aisle": location.aisle,
            "pick_events": 0,
            "short_events": 0,
            "damaged_events": 0,
            "skip_events": 0,
            "active_workers": 0,
        })
        row["active_workers"] += 1

    result = list(stats.values())
    for row in result:
        row["exception_rate_pct"] = round(
            ((row["short_events"] + row["damaged_events"]) / max(1, row["pick_events"] + row["short_events"] + row["damaged_events"])) * 100,
            2,
        )
        row["congestion_level"] = (
            "HIGH" if row["active_workers"] >= 6 else
            "MEDIUM" if row["active_workers"] >= 3 else
            "LOW"
        )
    return sorted(result, key=lambda r: (-r["pick_events"], r["domain"], r["aisle"] or 0))


def expiry_risk(db: Session, *, days: int = 7, site_id: str = "DEMO") -> list[dict[str, Any]]:
    today = date.today()
    cutoff = today + timedelta(days=max(0, days))
    lots = db.scalars(
        select(InventoryLot)
        .where(
            InventoryLot.qty > 0,
            InventoryLot.expires_on.is_not(None),
            InventoryLot.expires_on <= cutoff,
        )
        .order_by(InventoryLot.expires_on.asc())
    ).all()
    result = []
    for lot in lots:
        location = db.get(Location, lot.location_id)
        product = db.get(Product, lot.product_id)
        if not location or location.site_id != site_id:
            continue
        days_left = (lot.expires_on - today).days if lot.expires_on else None
        result.append({
            "lot_id": lot.id,
            "product_id": lot.product_id,
            "asin": product.asin if product else None,
            "title": product.title if product else "Unknown product",
            "location_id": lot.location_id,
            "lot_code": lot.lot_code,
            "expires_on": lot.expires_on.isoformat() if lot.expires_on else None,
            "days_left": days_left,
            "qty": lot.qty,
            "status": "EXPIRED" if days_left is not None and days_left < 0 else "EXPIRING",
        })
    return result


def simulate_order_route(
    db: Session,
    *,
    lines: list[dict[str, Any]],
    start_location_id: str | None = None,
) -> dict[str, Any]:
    chosen: list[dict[str, Any]] = []
    for spec in lines:
        product_id = str(spec["product_id"])
        qty = max(1, int(spec.get("qty", 1)))
        product = db.get(Product, product_id)
        if product is None:
            chosen.append({"product_id": product_id, "qty": qty, "status": "PRODUCT_NOT_FOUND"})
            continue
        balances = db.scalars(
            select(InventoryBalance).where(
                InventoryBalance.product_id == product_id,
                (InventoryBalance.qty_on_hand - InventoryBalance.qty_reserved) > 0,
            )
        ).all()
        options = []
        for balance in balances:
            location = db.get(Location, balance.location_id)
            if not location or not location.active or not location.pickable or not location.sellable:
                continue
            from .ops_platform import is_location_fulfillable
            if not is_location_fulfillable(db, product, location):
                continue
            available = max(0, balance.qty_on_hand - balance.qty_reserved)
            options.append((DOMAIN_ORDER.get(location_domain(location), 0), location.aisle or 9999, location, available))
        options.sort(key=lambda x: (x[0], x[1]))
        remaining = qty
        for _, _, location, available in options:
            if remaining <= 0:
                break
            take = min(remaining, available)
            chosen.append({
                "product_id": product_id,
                "title": product.title,
                "qty": take,
                "location_id": location.id,
                "domain": location_domain(location),
                "status": "ALLOCATABLE",
            })
            remaining -= take
        if remaining > 0:
            chosen.append({"product_id": product_id, "title": product.title, "qty": remaining, "status": "INSUFFICIENT_STOCK"})

    allocatable = [row for row in chosen if row.get("status") == "ALLOCATABLE"]
    cursor = start_location_id
    route = []
    distance = 0.0
    for rank in sorted({DOMAIN_ORDER.get(row["domain"], 0) for row in allocatable}):
        pending = [row for row in allocatable if DOMAIN_ORDER.get(row["domain"], 0) == rank]
        while pending:
            scored = [
                (shortest_location_distance(db, cursor, row["location_id"]), index, row)
                for index, row in enumerate(pending)
            ]
            scored.sort(key=lambda x: x[0])
            leg, index, row = scored[0]
            distance += leg
            route.append({**row, "distance_from_previous_m": round(leg, 2)})
            cursor = row["location_id"]
            pending.pop(index)
    units = sum(int(row["qty"]) for row in allocatable)
    return {
        "route": route,
        "allocation": chosen,
        "estimated_distance_m": round(distance, 2),
        "estimated_seconds": int(math.ceil(distance / 1.2 + units * 12)),
        "allocatable": all(row.get("status") != "INSUFFICIENT_STOCK" and row.get("status") != "PRODUCT_NOT_FOUND" for row in chosen),
        "changes_inventory": False,
    }


def handover_pick_task(
    db: Session,
    *,
    task: PickTask,
    to_user_id: str,
    manager_id: str,
    reason: str,
    to_device_id: str | None = None,
) -> TaskHandover:
    if task.status not in {TaskStatus.ACCEPTED.value, TaskStatus.PICKING.value}:
        raise ValueError("Only active pick tasks can be handed over")
    if not task.assigned_user_id:
        raise ValueError("Task has no current picker")
    from_user_id = task.assigned_user_id
    if from_user_id == to_user_id:
        raise ValueError("Cannot hand a task to the same picker")

    from .ops_platform import acquire_pick_lease, release_pick_lease, set_worker_state, worker_dispatch_status

    to_user = db.get(User, to_user_id)
    if to_user is None:
        raise ValueError("Target picker not found")
    eligibility = worker_dispatch_status(db, to_user, task)
    if not eligibility["dispatchable"]:
        raise ValueError("Target picker is not eligible: " + ", ".join(eligibility["reasons"]))

    picked_by_old = db.scalar(
        select(func.count()).select_from(ScanEvent).where(
            ScanEvent.task_id == task.id,
            ScanEvent.user_id == from_user_id,
            ScanEvent.event_type == "PICK",
        )
    ) or 0

    release_pick_lease(db, task, reason="TASK_HANDOVER")
    task.assigned_user_id = to_user_id
    task.assigned_device_id = to_device_id
    task.status = TaskStatus.PICKING.value
    task.server_version += 1
    acquire_pick_lease(
        db,
        user_id=to_user_id,
        task_id=task.id,
        device_id=to_device_id,
        mode="HANDOVER",
    )
    set_worker_state(db, to_user_id, "PICKING", activity_ref=task.id, reason="TASK_HANDOVER", force=True)

    row = TaskHandover(
        task_id=task.id,
        from_user_id=from_user_id,
        to_user_id=to_user_id,
        authorized_by_user_id=manager_id,
        reason=reason,
        picked_units_before_handover=int(picked_by_old),
    )
    db.add(row)
    db.flush()
    return row


def incident_center(db: Session, *, site_id: str = "DEMO") -> dict[str, Any]:
    incidents = db.scalars(
        select(OperationalIncident)
        .where(OperationalIncident.site_id == site_id, OperationalIncident.status == "OPEN")
        .order_by(OperationalIncident.created_at.desc())
        .limit(200)
    ).all()
    alerts = db.scalars(
        select(InventoryAlert)
        .where(InventoryAlert.status == "OPEN")
        .order_by(InventoryAlert.created_at.desc())
        .limit(100)
    ).all()
    overdue_stow = []
    shipments = db.scalars(
        select(__import__("app.models_ops", fromlist=["Shipment"]).Shipment).where(
            __import__("app.models_ops", fromlist=["Shipment"]).Shipment.status.not_in(["COMPLETED", "CANCELLED"]),
            __import__("app.models_ops", fromlist=["Shipment"]).Shipment.opened_at.is_not(None),
        )
    ).all()
    now = now_utc()
    for shipment in shipments:
        elapsed = int((now - _aware(shipment.opened_at)).total_seconds() // 60)
        if elapsed > shipment.target_stow_minutes:
            overdue_stow.append({
                "shipment_id": shipment.id,
                "label": shipment.label,
                "domain": shipment.storage_domain,
                "elapsed_minutes": elapsed,
                "target_stow_minutes": shipment.target_stow_minutes,
            })

    return {
        "incidents": [
            {
                "id": row.id,
                "type": row.incident_type,
                "severity": row.severity,
                "scope_type": row.scope_type,
                "scope_value": row.scope_value,
                "source_ref": row.source_ref,
                "details": json.loads(row.details_json or "{}"),
                "created_at": row.created_at.isoformat(),
            }
            for row in incidents
        ],
        "inventory_alerts": [
            {
                "id": row.id,
                "type": row.alert_type,
                "severity": row.severity,
                "product_id": row.product_id,
                "location_id": row.location_id,
                "details": json.loads(row.details_json or "{}"),
                "created_at": row.created_at.isoformat(),
            }
            for row in alerts
        ],
        "overdue_stow": overdue_stow,
    }


def set_guard_rule(
    db: Session,
    *,
    site_id: str,
    domain: str,
    rule_type: str,
    enabled: bool,
    config: dict[str, Any],
    manager_id: str,
) -> FulfillmentGuardRule:
    value = domain.strip().upper()
    rule = db.scalar(
        select(FulfillmentGuardRule).where(
            FulfillmentGuardRule.site_id == site_id,
            FulfillmentGuardRule.domain == value,
            FulfillmentGuardRule.rule_type == rule_type,
        )
    )
    if rule is None:
        rule = FulfillmentGuardRule(site_id=site_id, domain=value, rule_type=rule_type)
        db.add(rule)
    rule.enabled = enabled
    rule.config_json = json.dumps(config or {}, separators=(",", ":"))
    rule.updated_by_user_id = manager_id
    rule.updated_at = now_utc()
    db.flush()
    return rule


def evaluate_guard_rules(db: Session, *, site_id: str = "DEMO") -> list[dict[str, Any]]:
    rules = db.scalars(
        select(FulfillmentGuardRule).where(
            FulfillmentGuardRule.site_id == site_id,
            FulfillmentGuardRule.enabled == True,  # noqa: E712
        )
    ).all()
    results = []
    for rule in rules:
        if rule.rule_type != "NO_QUALIFIED_HANDLER":
            results.append({"rule_id": rule.id, "action": "NOOP", "reason": "UNSUPPORTED_RULE_TYPE"})
            continue

        qualified_users = db.scalars(
            select(WorkerQualification.user_id).where(
                WorkerQualification.qualification == rule.domain,
                WorkerQualification.active == True,  # noqa: E712
            )
        ).all()
        on_shift = 0
        if qualified_users:
            on_shift = db.scalar(
                select(func.count()).select_from(ShiftSession).where(
                    ShiftSession.user_id.in_(qualified_users),
                    ShiftSession.status == "OPEN",
                )
            ) or 0

        auto_reason = f"AUTO_NO_QUALIFIED_HANDLER_{rule.domain}"
        hold = db.scalar(
            select(FulfillmentHold).where(
                FulfillmentHold.site_id == site_id,
                FulfillmentHold.scope_type == "DOMAIN",
                FulfillmentHold.scope_value == rule.domain,
                FulfillmentHold.reason == auto_reason,
                FulfillmentHold.active == True,  # noqa: E712
            )
        )
        if on_shift == 0 and hold is None:
            hold = FulfillmentHold(
                site_id=site_id,
                scope_type="DOMAIN",
                scope_value=rule.domain,
                reason=auto_reason,
                notes="Automatically paused because no qualified handler is clocked in.",
                active=True,
                hard_stop=False,
                starts_at=now_utc(),
                created_by_user_id=None,
            )
            db.add(hold)
            incident = OperationalIncident(
                incident_type="AUTO_FULFILLMENT_HOLD",
                severity="HIGH",
                site_id=site_id,
                scope_type="DOMAIN",
                scope_value=rule.domain,
                source_ref=rule.id,
                details_json=json.dumps({"reason": "NO_QUALIFIED_HANDLER"}, separators=(",", ":")),
            )
            db.add(incident)
            action = "PAUSED"
        elif on_shift > 0 and hold is not None:
            hold.active = False
            hold.ended_at = now_utc()
            action = "RESUMED"
        else:
            action = "UNCHANGED"
        results.append({
            "rule_id": rule.id,
            "domain": rule.domain,
            "rule_type": rule.rule_type,
            "qualified_workers_on_shift": int(on_shift),
            "action": action,
        })
    db.flush()
    return results


def create_cycle_count_from_alert(
    db: Session,
    *,
    alert_id: str,
    user_id: str,
    manager_id: str,
) -> CycleCountSession:
    alert = db.get(InventoryAlert, alert_id)
    if alert is None or not alert.location_id:
        raise ValueError("Alert with a location is required")
    existing = db.scalar(
        select(CycleCountSession).where(
            CycleCountSession.location_id == alert.location_id,
            CycleCountSession.status == "OPEN",
        )
    )
    if existing:
        return existing
    session = CycleCountSession(location_id=alert.location_id, user_id=user_id)
    db.add(session)
    alert.status = "ASSIGNED_COUNT"
    incident = OperationalIncident(
        incident_type="CYCLE_COUNT_FROM_ALERT",
        severity=alert.severity,
        scope_type="BIN",
        scope_value=alert.location_id,
        source_ref=alert.id,
        created_by_user_id=manager_id,
        details_json=json.dumps({"assigned_user_id": user_id}, separators=(",", ":")),
    )
    db.add(incident)
    db.flush()
    return session
