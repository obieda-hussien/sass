from __future__ import annotations

from datetime import date, datetime
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
    must_change_password: bool = False


class HeartbeatRequest(BaseModel):
    current_task_id: str | None = None
    app_version: str | None = None
    connectivity: str = "ONLINE"
    battery_percent: int | None = Field(default=None, ge=0, le=100)
    last_location_id: str | None = None
    activity: str | None = Field(default=None, max_length=80)


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


class ShortPickRequest(BaseModel):
    event_id: str
    client_seq: int = Field(gt=0)
    task_item_id: str
    qty: int = Field(gt=0)
    reason: str = "MISSING_AT_LOCATION"


class RecoveryStowRequest(BaseModel):
    event_id: str
    product_id: str
    qty: int = Field(gt=0)
    destination_location_id: str



class ForgotPasswordRequest(BaseModel):
    identifier: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=6, max_length=10, pattern=r"^\\d{6,10}$")


class EmployeeCreateRequest(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    password: str | None = Field(default=None, min_length=6, max_length=10, pattern=r"^\\d{6,10}$")
    role: str = "PICKER"
    employee_code: str = Field(min_length=2, max_length=40)
    full_name: str = Field(min_length=2, max_length=160)
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    job_title: str = "Picker"
    department: str = "Operations"
    hire_date: date | None = None
    employment_status: str = "ACTIVE"
    currency: str = "EGP"
    base_salary_cents: int = Field(default=0, ge=0)
    overtime_rate_cents_per_hour: int = Field(default=0, ge=0)
    scheduled_start_minutes: int | None = Field(default=None, ge=0, le=1439)
    grace_minutes: int = Field(default=10, ge=0, le=240)
    notes: str | None = None


class EmployeeUpdateRequest(BaseModel):
    role: str | None = None
    active: bool | None = None
    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    job_title: str | None = None
    department: str | None = None
    hire_date: date | None = None
    employment_status: str | None = None
    currency: str | None = None
    base_salary_cents: int | None = Field(default=None, ge=0)
    overtime_rate_cents_per_hour: int | None = Field(default=None, ge=0)
    scheduled_start_minutes: int | None = Field(default=None, ge=0, le=1439)
    grace_minutes: int | None = Field(default=None, ge=0, le=240)
    notes: str | None = None


class AttendanceCreateRequest(BaseModel):
    scheduled_start_at: datetime
    clock_in_at: datetime
    clock_out_at: datetime | None = None
    overtime_minutes: int = Field(default=0, ge=0)
    status: str = "APPROVED"
    notes: str | None = None


class PerformanceEventCreateRequest(BaseModel):
    event_type: str
    order_id: str | None = None
    task_id: str | None = None
    minutes: int = Field(default=0, ge=0)
    source: str = "MANUAL"
    notes: str | None = None
    occurred_at: datetime | None = None


class PayAdjustmentCreateRequest(BaseModel):
    kind: str = "ADJUSTMENT"
    amount_cents: int
    reason: str = Field(min_length=2, max_length=240)
    approved: bool = False


class TemporaryPasswordRequest(BaseModel):
    password: str | None = Field(default=None, min_length=6, max_length=10, pattern=r"^\\d{6,10}$")


class PromotionRequest(BaseModel):
    to_role: str
    reason: str = Field(min_length=2, max_length=300)
    new_base_salary_cents: int | None = Field(default=None, ge=0)
    effective_at: datetime | None = None


class AdminAccountUpdateRequest(BaseModel):
    username: str = Field(min_length=3, max_length=80, pattern=r"^[A-Za-z0-9._-]+$")


class AdminSetPinRequest(BaseModel):
    password: str | None = Field(default=None, min_length=6, max_length=10, pattern=r"^\d{6,10}$")
    require_change_on_next_login: bool = True


class AdminDeactivateUserRequest(BaseModel):
    reason: str = Field(min_length=2, max_length=240)
