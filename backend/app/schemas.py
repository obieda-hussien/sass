from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ProductCreate(BaseModel):
    sku: str
    title: str
    barcode: str
    temperature_class: str = "AMBIENT"
    handling_class: str = "STANDARD"


class LocationCreate(BaseModel):
    code: str
    handling_class_override: str | None = None
    pickable: bool = True
    stowable: bool = True


class InventoryAdjustRequest(BaseModel):
    event_id: str
    product_sku: str
    location_code: str
    delta: int
    reason: str = "ADJUSTMENT"
    actor_id: str | None = None
    device_id: str | None = None


class MoveRequest(BaseModel):
    event_id: str
    product_sku: str
    source_location: str
    destination_location: str
    quantity: int = Field(gt=0)
    reason: str = "BOH_MOVE"
    actor_id: str | None = None
    device_id: str | None = None


class OrderLineCreate(BaseModel):
    sku: str
    quantity: int = Field(gt=0)


class OrderCreate(BaseModel):
    external_ref: str
    lines: list[OrderLineCreate]
    priority: int = 0


class OfferRequest(BaseModel):
    associate_id: str


class AcceptTaskRequest(BaseModel):
    associate_id: str
    device_id: str


class ScanPickRequest(BaseModel):
    event_id: str
    task_line_id: str
    associate_id: str
    device_id: str
    client_sequence: int = Field(ge=1)
    client_task_version: int = Field(ge=1)
    location_code: str
    barcode: str
    quantity: int = Field(gt=0)


class ShortPickRequest(BaseModel):
    event_id: str
    task_line_id: str
    associate_id: str
    device_id: str
    client_sequence: int = Field(ge=1)
    client_task_version: int = Field(ge=1)
    quantity: int = Field(gt=0)
    reason: str


class CancelTaskRequest(BaseModel):
    reason: str
    actor_id: str | None = None


class StageRequest(BaseModel):
    location_code: str
    associate_id: str
    device_id: str


class HandoffRequest(BaseModel):
    associate_id: str
    device_id: str
    rider_ref: str | None = None


class HeartbeatRequest(BaseModel):
    device_id: str
    associate_id: str
    active_task_id: str | None = None
    network_online: bool = True
    client_time: datetime | None = None


class DowntimeRequest(BaseModel):
    event_id: str
    kind: str
    task_id: str | None = None
    associate_id: str | None = None
    device_id: str | None = None
    detail: str | None = None
    ended: bool = False


class ReconcileRequest(BaseModel):
    device_id: str
    associate_id: str
    task_id: str | None = None
    last_known_version: int | None = None
    pending_event_ids: list[str] = []


class UnpackRequest(BaseModel):
    event_id: str
    product_sku: str
    quantity: int = Field(gt=0)
    temperature_class: str
    actor_id: str
    device_id: str


class DamageRequest(BaseModel):
    event_id: str
    product_sku: str
    source_location: str
    quantity: int = Field(gt=0)
    reason: str
    actor_id: str
    device_id: str


class CountRequest(BaseModel):
    event_id: str
    product_sku: str
    location_code: str
    counted_quantity: int = Field(ge=0)
    actor_id: str
    device_id: str
