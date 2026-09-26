from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def _uuid() -> str:
    return str(uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Product(Base):
    __tablename__ = "products"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    sku: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(240))
    temperature_class: Mapped[str] = mapped_column(String(24), default="AMBIENT")
    handling_class: Mapped[str] = mapped_column(String(24), default="STANDARD")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Barcode(Base):
    __tablename__ = "barcodes"

    code: Mapped[str] = mapped_column(String(80), primary_key=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), index=True)


class Location(Base):
    __tablename__ = "locations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    code: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(24), default="STORAGE")
    floor: Mapped[int | None] = mapped_column(Integer)
    fixture: Mapped[str | None] = mapped_column(String(16))
    aisle: Mapped[int | None] = mapped_column(Integer)
    level: Mapped[str | None] = mapped_column(String(8))
    slot: Mapped[int | None] = mapped_column(Integer)
    temperature_class: Mapped[str] = mapped_column(String(24), default="AMBIENT")
    handling_class: Mapped[str] = mapped_column(String(24), default="STANDARD")
    pickable: Mapped[bool] = mapped_column(Boolean, default=True)
    stowable: Mapped[bool] = mapped_column(Boolean, default=True)


class InventoryBalance(Base):
    __tablename__ = "inventory_balances"
    __table_args__ = (
        UniqueConstraint("product_id", "location_id", name="uq_inventory_product_location"),
        Index("ix_inventory_location_product", "location_id", "product_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), index=True)
    location_id: Mapped[str] = mapped_column(ForeignKey("locations.id"), index=True)
    on_hand: Mapped[int] = mapped_column(Integer, default=0)
    reserved: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[int] = mapped_column(Integer, default=0)

    product: Mapped[Product] = relationship()
    location: Mapped[Location] = relationship()

    @property
    def available(self) -> int:
        return self.on_hand - self.reserved


class InventoryMovement(Base):
    __tablename__ = "inventory_movements"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    event_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), index=True)
    quantity: Mapped[int] = mapped_column(Integer)
    source_location_id: Mapped[str | None] = mapped_column(ForeignKey("locations.id"))
    destination_location_id: Mapped[str | None] = mapped_column(ForeignKey("locations.id"))
    reason: Mapped[str] = mapped_column(String(48))
    actor_id: Mapped[str | None] = mapped_column(String(80))
    device_id: Mapped[str | None] = mapped_column(String(80))
    task_id: Mapped[str | None] = mapped_column(String(36), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Associate(Base):
    __tablename__ = "associates"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(120))
    state: Mapped[str] = mapped_column(String(32), default="OFFLINE")
    active_task_id: Mapped[str | None] = mapped_column(String(36), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class DeviceSession(Base):
    __tablename__ = "device_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    device_id: Mapped[str] = mapped_column(String(80), index=True)
    associate_id: Mapped[str] = mapped_column(String(80), index=True)
    refresh_token_hash: Mapped[str] = mapped_column(String(128), unique=True)
    active_task_id: Mapped[str | None] = mapped_column(String(36), index=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    last_heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    external_ref: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    state: Mapped[str] = mapped_column(String(32), default="CREATED")
    priority: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    lines: Mapped[list["OrderLine"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )


class OrderLine(Base):
    __tablename__ = "order_lines"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), index=True)
    requested_qty: Mapped[int] = mapped_column(Integer)
    allocated_qty: Mapped[int] = mapped_column(Integer, default=0)
    picked_qty: Mapped[int] = mapped_column(Integer, default=0)

    order: Mapped[Order] = relationship(back_populates="lines")
    product: Mapped[Product] = relationship()


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), unique=True, index=True)
    state: Mapped[str] = mapped_column(String(32), default="READY", index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    associate_id: Mapped[str | None] = mapped_column(String(80), index=True)
    offered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(String(240))
    recovery_reason: Mapped[str | None] = mapped_column(String(240))

    order: Mapped[Order] = relationship()
    lines: Mapped[list["TaskLine"]] = relationship(
        back_populates="task", cascade="all, delete-orphan", order_by="TaskLine.sequence"
    )


class TaskLine(Base):
    __tablename__ = "task_lines"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    order_line_id: Mapped[str] = mapped_column(ForeignKey("order_lines.id"), index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), index=True)
    location_id: Mapped[str] = mapped_column(ForeignKey("locations.id"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    required_qty: Mapped[int] = mapped_column(Integer)
    picked_qty: Mapped[int] = mapped_column(Integer, default=0)
    short_qty: Mapped[int] = mapped_column(Integer, default=0)

    task: Mapped[Task] = relationship(back_populates="lines")
    product: Mapped[Product] = relationship()
    location: Mapped[Location] = relationship()


class ScanEvent(Base):
    __tablename__ = "scan_events"
    __table_args__ = (
        UniqueConstraint("task_id", "client_sequence", name="uq_scan_task_client_sequence"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    event_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    task_line_id: Mapped[str] = mapped_column(ForeignKey("task_lines.id"), index=True)
    associate_id: Mapped[str] = mapped_column(String(80))
    device_id: Mapped[str] = mapped_column(String(80))
    client_sequence: Mapped[int] = mapped_column(Integer)
    client_task_version: Mapped[int] = mapped_column(Integer)
    quantity: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default="COMMITTED")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class DowntimeEvent(Base):
    __tablename__ = "downtime_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    task_id: Mapped[str | None] = mapped_column(String(36), index=True)
    associate_id: Mapped[str | None] = mapped_column(String(80), index=True)
    device_id: Mapped[str | None] = mapped_column(String(80), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    detail: Mapped[str | None] = mapped_column(Text)


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (Index("ix_outbox_unpublished", "published_at", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    topic: Mapped[str] = mapped_column(String(120))
    aggregate_type: Mapped[str] = mapped_column(String(80))
    aggregate_id: Mapped[str] = mapped_column(String(80), index=True)
    payload_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
