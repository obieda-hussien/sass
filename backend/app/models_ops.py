from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from .models import new_id, utcnow


class WorkerRuntimeState(Base):
    __tablename__ = "worker_runtime_states"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    state: Mapped[str] = mapped_column(String(40), default="AVAILABLE", index=True)
    activity_ref: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(String(240), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class WorkerStateEvent(Base):
    __tablename__ = "worker_state_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    from_state: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    to_state: Mapped[str] = mapped_column(String(40), index=True)
    activity_ref: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(String(240), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class WorkerQualification(Base):
    __tablename__ = "worker_qualifications"
    __table_args__ = (UniqueConstraint("user_id", "qualification", name="uq_worker_qualification"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    qualification: Mapped[str] = mapped_column(String(40), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    granted_by_user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ActivePickLease(Base):
    """Hard one-picker/one-order invariant.

    A user can own at most one active pick lease and a task can have at most one owner.
    The unique constraints are the last line of defense against concurrent claims.
    """

    __tablename__ = "active_pick_leases"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("pick_tasks.id"), unique=True, index=True)
    device_id: Mapped[Optional[str]] = mapped_column(ForeignKey("devices.id"), nullable=True)
    mode: Mapped[str] = mapped_column(String(24), default="CLAIM")
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PickOffer(Base):
    __tablename__ = "pick_offers"
    __table_args__ = (UniqueConstraint("task_id", "user_id", name="uq_pick_offer_user"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(ForeignKey("pick_tasks.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(24), default="OPEN", index=True)
    offered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class FulfillmentHold(Base):
    __tablename__ = "fulfillment_holds"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    site_id: Mapped[str] = mapped_column(String(32), default="DEMO", index=True)
    scope_type: Mapped[str] = mapped_column(String(24), index=True)
    scope_value: Mapped[str] = mapped_column(String(120), index=True)
    reason: Mapped[str] = mapped_column(String(48), index=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    hard_stop: Mapped[bool] = mapped_column(Boolean, default=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), nullable=True)
    ended_by_user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class OrderBag(Base):
    __tablename__ = "order_bags"
    __table_args__ = (UniqueConstraint("order_id", "bag_no", name="uq_order_bag_number"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), index=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("pick_tasks.id"), index=True)
    bag_no: Mapped[int] = mapped_column(Integer)
    spoo_code: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    closed_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    closed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class PickException(Base):
    __tablename__ = "pick_exceptions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    event_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("pick_tasks.id"), index=True)
    task_item_id: Mapped[str] = mapped_column(ForeignKey("pick_task_items.id"), index=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    location_id: Mapped[str] = mapped_column(ForeignKey("locations.id"), index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), index=True)
    exception_type: Mapped[str] = mapped_column(String(32), index=True)
    reason: Mapped[str] = mapped_column(String(80), index=True)
    qty: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class InventoryAlert(Base):
    __tablename__ = "inventory_alerts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    alert_type: Mapped[str] = mapped_column(String(40), index=True)
    product_id: Mapped[Optional[str]] = mapped_column(ForeignKey("products.id"), nullable=True, index=True)
    location_id: Mapped[Optional[str]] = mapped_column(ForeignKey("locations.id"), nullable=True, index=True)
    severity: Mapped[str] = mapped_column(String(16), default="MEDIUM")
    status: Mapped[str] = mapped_column(String(24), default="OPEN", index=True)
    source_ref: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    details_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class ReplenishmentTask(Base):
    __tablename__ = "replenishment_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), index=True)
    source_location_id: Mapped[str] = mapped_column(ForeignKey("locations.id"), index=True)
    destination_location_id: Mapped[str] = mapped_column(ForeignKey("locations.id"), index=True)
    qty: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default="READY", index=True)
    trigger: Mapped[str] = mapped_column(String(40), default="SHORT")
    source_ref: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    assigned_user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class Shipment(Base):
    __tablename__ = "shipments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    label: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    shipment_type: Mapped[str] = mapped_column(String(40), default="VENDOR", index=True)
    storage_domain: Mapped[str] = mapped_column(String(24), default="AMBIENT", index=True)
    status: Mapped[str] = mapped_column(String(24), default="CREATED", index=True)
    dock_ref: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    inbound_location_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    expected_units: Mapped[int] = mapped_column(Integer, default=0)
    received_units: Mapped[int] = mapped_column(Integer, default=0)
    damaged_units: Mapped[int] = mapped_column(Integer, default=0)
    missing_units: Mapped[int] = mapped_column(Integer, default=0)
    target_stow_minutes: Mapped[int] = mapped_column(Integer, default=120)
    opened_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    received_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class ShipmentLine(Base):
    __tablename__ = "shipment_lines"
    __table_args__ = (UniqueConstraint("shipment_id", "product_id", name="uq_shipment_product"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    shipment_id: Mapped[str] = mapped_column(ForeignKey("shipments.id"), index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), index=True)
    expected_qty: Mapped[int] = mapped_column(Integer, default=0)
    received_qty: Mapped[int] = mapped_column(Integer, default=0)
    damaged_qty: Mapped[int] = mapped_column(Integer, default=0)
    missing_qty: Mapped[int] = mapped_column(Integer, default=0)
    lot_code: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    expires_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)


class ReceivingSession(Base):
    __tablename__ = "receiving_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    shipment_id: Mapped[str] = mapped_column(ForeignKey("shipments.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id"), index=True)
    status: Mapped[str] = mapped_column(String(24), default="OPEN", index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class StowTask(Base):
    __tablename__ = "stow_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    shipment_id: Mapped[str] = mapped_column(ForeignKey("shipments.id"), index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), index=True)
    source_location_id: Mapped[str] = mapped_column(ForeignKey("locations.id"), index=True)
    destination_location_id: Mapped[Optional[str]] = mapped_column(ForeignKey("locations.id"), nullable=True)
    qty: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default="READY", index=True)
    assigned_user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class InventoryLot(Base):
    __tablename__ = "inventory_lots"
    __table_args__ = (UniqueConstraint("product_id", "location_id", "lot_code", name="uq_inventory_lot"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), index=True)
    location_id: Mapped[str] = mapped_column(ForeignKey("locations.id"), index=True)
    lot_code: Mapped[str] = mapped_column(String(80))
    expires_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True, index=True)
    qty: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ShiftSession(Base):
    __tablename__ = "shift_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    scheduled_start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    scheduled_end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    clock_in_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    clock_out_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="OPEN", index=True)
    late_minutes: Mapped[int] = mapped_column(Integer, default=0)
    early_leave_minutes: Mapped[int] = mapped_column(Integer, default=0)
    overtime_minutes: Mapped[int] = mapped_column(Integer, default=0)
    worked_minutes: Mapped[int] = mapped_column(Integer, default=0)
    attendance_entry_id: Mapped[Optional[str]] = mapped_column(ForeignKey("attendance_entries.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AttendanceComputation(Base):
    __tablename__ = "attendance_computations"

    attendance_entry_id: Mapped[str] = mapped_column(ForeignKey("attendance_entries.id"), primary_key=True)
    scheduled_end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    early_leave_minutes: Mapped[int] = mapped_column(Integer, default=0)
    worked_minutes: Mapped[int] = mapped_column(Integer, default=0)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PayrollPolicy(Base):
    __tablename__ = "payroll_policies"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    late_deduction_cents_per_minute: Mapped[int] = mapped_column(Integer, default=0)
    early_leave_deduction_cents_per_minute: Mapped[int] = mapped_column(Integer, default=0)
    auto_apply_attendance_deductions: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_by_user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class DeviceTelemetry(Base):
    __tablename__ = "device_telemetry"

    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id"), primary_key=True)
    battery_percent: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    connectivity: Mapped[Optional[str]] = mapped_column(String(24), nullable=True)
    last_location_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class WarehouseNode(Base):
    __tablename__ = "warehouse_nodes"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    site_id: Mapped[str] = mapped_column(String(32), default="DEMO", index=True)
    name: Mapped[str] = mapped_column(String(120))
    node_type: Mapped[str] = mapped_column(String(32), default="PICK", index=True)
    domain: Mapped[Optional[str]] = mapped_column(String(24), nullable=True, index=True)
    aisle: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    x_m: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    y_m: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class WarehouseEdge(Base):
    __tablename__ = "warehouse_edges"
    __table_args__ = (UniqueConstraint("site_id", "from_node_id", "to_node_id", name="uq_warehouse_edge"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    site_id: Mapped[str] = mapped_column(String(32), default="DEMO", index=True)
    from_node_id: Mapped[str] = mapped_column(ForeignKey("warehouse_nodes.id"), index=True)
    to_node_id: Mapped[str] = mapped_column(ForeignKey("warehouse_nodes.id"), index=True)
    distance_m: Mapped[float] = mapped_column(Float, default=1.0)
    one_way: Mapped[bool] = mapped_column(Boolean, default=False)
    congestion_factor: Mapped[float] = mapped_column(Float, default=1.0)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class LocationOperationalProfile(Base):
    __tablename__ = "location_operational_profiles"

    location_id: Mapped[str] = mapped_column(ForeignKey("locations.id"), primary_key=True)
    node_id: Mapped[Optional[str]] = mapped_column(ForeignKey("warehouse_nodes.id"), nullable=True, index=True)
    capacity_units: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    average_pick_seconds: Mapped[float] = mapped_column(Float, default=12.0)
    route_sequence_override: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class WorkerDispatchProfile(Base):
    __tablename__ = "worker_dispatch_profiles"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    home_domain: Mapped[Optional[str]] = mapped_column(String(24), nullable=True)
    allowed_domains_json: Mapped[str] = mapped_column(Text, default="[]")
    updated_by_user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class TaskHandover(Base):
    __tablename__ = "task_handovers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(ForeignKey("pick_tasks.id"), index=True)
    from_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    to_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    authorized_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    reason: Mapped[str] = mapped_column(String(200))
    picked_units_before_handover: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class OperationalIncident(Base):
    __tablename__ = "operational_incidents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    incident_type: Mapped[str] = mapped_column(String(48), index=True)
    severity: Mapped[str] = mapped_column(String(16), default="MEDIUM", index=True)
    site_id: Mapped[str] = mapped_column(String(32), default="DEMO", index=True)
    scope_type: Mapped[Optional[str]] = mapped_column(String(24), nullable=True)
    scope_value: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    source_ref: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(24), default="OPEN", index=True)
    details_json: Mapped[str] = mapped_column(Text, default="{}")
    created_by_user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), nullable=True)
    resolved_by_user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class FulfillmentGuardRule(Base):
    __tablename__ = "fulfillment_guard_rules"
    __table_args__ = (UniqueConstraint("site_id", "domain", "rule_type", name="uq_fulfillment_guard_rule"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    site_id: Mapped[str] = mapped_column(String(32), default="DEMO", index=True)
    domain: Mapped[str] = mapped_column(String(24), index=True)
    rule_type: Mapped[str] = mapped_column(String(48), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    config_json: Mapped[str] = mapped_column(Text, default="{}")
    updated_by_user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
