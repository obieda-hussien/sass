# FulfillOS build report — v0.3 operations platform

## Implemented

### Dispatch and picker ownership

- Hard one picker → one active order invariant with database-backed pick leases.
- Broadcast offers to every eligible AVAILABLE picker.
- Atomic first-winner claim; later accepts cannot steal the order.
- Supervisor direct assignment only to eligible workers, with safe timeout release.
- User-wide active-task recovery, not device-only ownership.
- Work states for picking, break, receiving variants, stow, unpack, cycle count, expiry/bin work, training and end-shift.
- HAZ / HRV qualifications included in dispatch eligibility.
- Device battery, connectivity and last-location telemetry on the dispatch board.

### Picking, bags and Order Explorer

- Warm/ambient path first, chilled next and frozen last.
- FEFO-aware inventory selection when lot expiry data exists.
- Durable PDA PICK, SHORT, SKIP and DAMAGED events.
- SKIP moves a line to the end of the current route; SHORT is a confirmed shortage.
- Damaged units move to DMG.
- Repeated shortage evidence creates inventory alerts and replenishment candidates.
- One or more bag/SPOO closes per order.
- Full SPOO stored server-side; last four shown in picker completion UI.
- Completion summary includes lines, quantities and bags.
- Search by order/external id, picker username, full SPOO or suffix, and date/time window.

### Fulfillment availability

- SITE → DOMAIN → ZONE → AISLE → BIN → SKU holds.
- Soft holds block new orderability/allocation while already allocated work can continue.
- Emergency hard-stop mode also blocks affected pick scans.
- Scheduled starts/expiry.
- Physical stock, fulfillable stock and blocked stock are reported separately.
- A SKU remains orderable when enabled alternate stock is available.
- Impact preview counts affected locations, SKUs, units and full-unavailability.

### Inbound, receiving and stow

- Shipment model with configurable shipment type.
- Ambient, chilled, frozen, HAZ, HRV and produce domains.
- Dock check-in, receiving session, good/damaged/missing reconciliation.
- HAZ/HRV worker qualification enforcement.
- Inbound location per shipment, lot/expiry capture and cold-chain target-stow timer.
- Stow tasks plus compatible destination recommendations.
- Existing Unpack and Cycle Count automatically block dispatch while active.

### Workforce and payroll

- Shift clock-in/out calculates late-after-grace, early leave, worked minutes and overtime.
- Overtime pay preview.
- Explicit per-worker late/early-leave deduction policy.
- Attendance deductions auto-apply only when that policy enables them.
- SENIOR_PICKER is a supported role, but promotion/pay are never inferred from a score.
- Objective performance metrics: orders, units, bags, late-SLAM count/rate and average pick time.

### Operations intelligence and clients

- Demand/velocity slotting suggestions; no automatic stock relocation.
- Web Operations Console for dispatch, holds, Order Explorer, performance, inbound and slotting.
- Android PDA broadcast offers, atomic accept, skip/short/damage, multi-bag SPOO close and completion summary.
- PostgreSQL migration: backend/migrations/0002_ops_platform.sql.

## Validation

The branch includes focused backend tests for holds vs physical stock, first-winner claims, one-order ownership, break-state blocking, SPOO search, shortage automation, receiving/stow transitions and shift/payroll time calculations. GitHub Actions is the authoritative backend + Android build validation.
