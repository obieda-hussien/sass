from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid.uuid4())


class TemperatureClass(str, enum.Enum):
    AMBIENT = "AMBIENT"
    CHILLED = "CHILLED"
    FROZEN = "FROZEN"


class HandlingClass(str, enum.Enum):
    STANDARD = "STANDARD"
    HAZ = "HAZ"
    HRV = "HRV"
    DAMAGE = "DAMAGE"
    RETURNS = "RETURNS"
    SPECIAL = "SPECIAL"


class OrderStatus(str, enum.Enum):
    CREATED = "CREATED"
    ALLOCATED = "ALLOCATED"
    OFFERED = "OFFERED"
    PICKING = "PICKING"
    PICKED = "PICKED"
    PACK_RACK = "PACK_RACK"
    STAGED = "STAGED"
    HANDOFF_READY = "HANDOFF_READY"
    HANDED_OFF = "HANDED_OFF"
    COMPLETED = "COMPLETED"
    CANCEL_PENDING = "CANCEL_PENDING"
    CANCELLED = "CANCELLED"
    CANCELLED_RECOVERY = "CANCELLED_RECOVERY"
    RETURN_REQUIRED = "RETURN_REQUIRED"


class TaskStatus(str, enum.Enum):
    READY = "READY"
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    PICKING = "PICKING"
    PICKED = "PICKED"
    PACK_RACK = "PACK_RACK"
    STAGED = "STAGED"
    HANDOFF_READY = "HANDOFF_READY"
    HANDED_OFF = "HANDED_OFF"
    COMPLETED = "COMPLETED"
    CANCEL_PENDING = "CANCEL_PENDING"
    CANCELLED = "CANCELLED"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    role: Mapped[str] = mapped_column(String(32), default="PICKER")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Device(Base):
    __tablename__ = "devices"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    trusted: Mapped[bool] = mapped_column(Boolean, default=True)
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), nullable=True)
    app_version: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="OFFLINE")


class SessionToken(Base):
    __tablename__ = "session_tokens"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id"), index=True)
    access_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    refresh_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    access_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    refresh_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Product(Base):
    __tablename__ = "products"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    asin: Mapped[str] = mapped_column(String(24), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(240))
    temperature_class: Mapped[str] = mapped_column(String(16), default=TemperatureClass.AMBIENT.value)
    handling_class: Mapped[str] = mapped_column(String(16), default=HandlingClass.STANDARD.value)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Barcode(Base):
    __tablename__ = "barcodes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), index=True)
    product: Mapped[Product] = relationship()


class Location(Base):
    __tablename__ = "locations"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    site_id: Mapped[str] = mapped_column(String(32), default="DEMO")
    floor: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    classification: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    fixture_type: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    aisle: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    level: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    slot: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    temperature_class: Mapped[str] = mapped_column(String(16), default=TemperatureClass.AMBIENT.value)
    handling_class: Mapped[str] = mapped_column(String(16), default=HandlingClass.STANDARD.value)
    pickable: Mapped[bool] = mapped_column(Boolean, default=True)
    stowable: Mapped[bool] = mapped_column(Boolean, default=True)
    logical: Mapped[bool] = mapped_column(Boolean, default=False)
    sellable: Mapped[bool] = mapped_column(Boolean, default=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    color_code: Mapped[Optional[str]] = mapped_column(String(24), nullable=True)


class InventoryBalance(Base):
    __tablename__ = "inventory_balances"
    __table_args__ = (UniqueConstraint("location_id", "product_id", name="uq_inventory_balance"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    location_id: Mapped[str] = mapped_column(ForeignKey("locations.id"), index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), index=True)
    qty_on_hand: Mapped[int] = mapped_column(Integer, default=0)
    qty_reserved: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class InventoryMovement(Base):
    __tablename__ = "inventory_movements"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    event_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), index=True)
    qty: Mapped[int] = mapped_column(Integer)
    source_location_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    destination_location_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    reason: Mapped[str] = mapped_column(String(40))
    order_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    task_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    user_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    device_id: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    external_ref: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, unique=True)
    status: Mapped[str] = mapped_column(String(32), default=OrderStatus.CREATED.value, index=True)
    priority: Mapped[int] = mapped_column(Integer, default=100)
    cancellation_reason: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    recovery_required: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class OrderLine(Base):
    __tablename__ = "order_lines"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), index=True)
    requested_qty: Mapped[int] = mapped_column(Integer)
    allocated_qty: Mapped[int] = mapped_column(Integer, default=0)
    picked_qty: Mapped[int] = mapped_column(Integer, default=0)
    shorted_qty: Mapped[int] = mapped_column(Integer, default=0)


class PickTask(Base):
    __tablename__ = "pick_tasks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default=TaskStatus.READY.value, index=True)
    assigned_user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), nullable=True)
    assigned_device_id: Mapped[Optional[str]] = mapped_column(ForeignKey("devices.id"), nullable=True)
    stage_location_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    handoff_ref: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    expected_units: Mapped[int] = mapped_column(Integer, default=0)
    server_version: Mapped[int] = mapped_column(Integer, default=0)
    client_high_water_seq: Mapped[int] = mapped_column(Integer, default=0)
    offered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class PickTaskItem(Base):
    __tablename__ = "pick_task_items"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(ForeignKey("pick_tasks.id"), index=True)
    order_line_id: Mapped[str] = mapped_column(ForeignKey("order_lines.id"), index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), index=True)
    source_location_id: Mapped[str] = mapped_column(ForeignKey("locations.id"), index=True)
    planned_qty: Mapped[int] = mapped_column(Integer)
    picked_qty: Mapped[int] = mapped_column(Integer, default=0)
    sequence: Mapped[int] = mapped_column(Integer)


class ScanEvent(Base):
    __tablename__ = "scan_events"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("pick_tasks.id"), index=True)
    client_seq: Mapped[int] = mapped_column(Integer)
    device_id: Mapped[str] = mapped_column(String(80))
    user_id: Mapped[str] = mapped_column(String(36))
    event_type: Mapped[str] = mapped_column(String(32), default="PICK")
    status: Mapped[str] = mapped_column(String(24), default="ACKED")
    payload_json: Mapped[str] = mapped_column(Text)
    server_version_after: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DowntimeSegment(Base):
    __tablename__ = "downtime_segments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(ForeignKey("pick_tasks.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    source: Mapped[str] = mapped_column(String(32), default="SYSTEM")


class UnpackSession(Base):
    __tablename__ = "unpack_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    temperature_class: Mapped[str] = mapped_column(String(16))
    tote_location_id: Mapped[str] = mapped_column(ForeignKey("locations.id"), index=True)
    status: Mapped[str] = mapped_column(String(24), default="OPEN", index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class UnpackEntry(Base):
    __tablename__ = "unpack_entries"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("unpack_sessions.id"), index=True)
    event_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), index=True)
    qty: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CycleCountSession(Base):
    __tablename__ = "cycle_count_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    location_id: Mapped[str] = mapped_column(ForeignKey("locations.id"), index=True)
    status: Mapped[str] = mapped_column(String(24), default="OPEN", index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class CycleCountEntry(Base):
    __tablename__ = "cycle_count_entries"
    __table_args__ = (UniqueConstraint("session_id", "product_id", name="uq_cycle_count_product"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("cycle_count_sessions.id"), index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), index=True)
    system_qty: Mapped[int] = mapped_column(Integer)
    counted_qty: Mapped[int] = mapped_column(Integer)
    variance: Mapped[int] = mapped_column(Integer)
    applied: Mapped[bool] = mapped_column(Boolean, default=False)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    entity_type: Mapped[str] = mapped_column(String(40), index=True)
    entity_id: Mapped[str] = mapped_column(String(100), index=True)
    user_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    device_id: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
