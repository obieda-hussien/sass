from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str
    password: str
    device_id: str
    app_version: str | None = None


class RefreshRequest(BaseModel):
    refresh_token: str
    device_id: str


class SessionResponse(BaseModel):
    access_token: str
    refresh_token: str
    user_id: str
    username: str
    role: str
    device_id: str


class HeartbeatRequest(BaseModel):
    current_task_id: str | None = None
    app_version: str | None = None
    connectivity: str = "ONLINE"


class InventoryMoveRequest(BaseModel):
    event_id: str
    product_id: str
    qty: int = Field(gt=0)
    source_location_id: str | None = None
    destination_location_id: str | None = None
    reason: str
    order_id: str | None = None
    task_id: str | None = None


class OrderLineCreate(BaseModel):
    product_id: str
    qty: int = Field(gt=0)


class OrderCreate(BaseModel):
    external_ref: str | None = None
    priority: int = 100
    lines: list[OrderLineCreate]


class TaskOfferRequest(BaseModel):
    user_id: str
    device_id: str


class RejectOfferRequest(BaseModel):
    reason: str = "ASSOCIATE_REJECTED"


class PickScanRequest(BaseModel):
    event_id: str
    client_seq: int = Field(gt=0)
    task_item_id: str
    location_id: str
    product_id: str
    qty: int = Field(gt=0)
    barcode: str | None = None


class SyncEvent(BaseModel):
    event_id: str
    client_seq: int
    event_type: str = "PICK"
    payload: dict[str, Any]


class SyncBatchRequest(BaseModel):
    task_id: str
    events: list[SyncEvent]


class CancelRequest(BaseModel):
    reason: str = "CUSTOMER_CANCELLED"


class DowntimeRequest(BaseModel):
    kind: str
    source: str = "DEVICE"


class ReceiveRequest(BaseModel):
    event_id: str
    product_id: str
    qty: int = Field(gt=0)
    destination_location_id: str


class UnpackStartRequest(BaseModel):
    temperature_class: str


class UnpackScanRequest(BaseModel):
    event_id: str
    product_id: str
    qty: int = Field(gt=0)


class BOHMoveRequest(BaseModel):
    event_id: str
    product_id: str
    qty: int = Field(gt=0)
    source_location_id: str
    destination_location_id: str


class DamageRequest(BaseModel):
    event_id: str
    product_id: str
    qty: int = Field(gt=0)
    source_location_id: str
    reason: str


class CycleCountStartRequest(BaseModel):
    location_id: str


class CycleCountLineRequest(BaseModel):
    product_id: str
    counted_qty: int = Field(ge=0)


class CycleCountApplyRequest(BaseModel):
    reason: str = "CYCLE_COUNT_ADJUSTMENT"


class StageRequest(BaseModel):
    stage_location_id: str


class HandoffRequest(BaseModel):
    handoff_ref: str
