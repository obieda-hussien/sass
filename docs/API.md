# FulfillOS API surface — v0.5

This document groups the current public/internal API by responsibility. The FastAPI OpenAPI document remains the authoritative machine-readable contract.

Production base:

```text
https://fulfillos-nine.vercel.app/api
```

## Authentication and device session

```text
POST /auth/login
POST /auth/refresh
POST /auth/forgot-password
POST /auth/change-password
POST /auth/complete-first-login
POST /devices/heartbeat
```

Authentication is device-aware. Android uses access + refresh credentials and restores server-owned task state after process/device recovery.

## v0.5 identity/session behavior

Employee onboarding and manager resets use numeric PINs:

- accepted employee PIN length: 6–10 digits;
- generated temporary PIN: exactly six random digits;
- new employee accounts start with `must_change_password=true`;
- normal warehouse API dependencies return HTTP 428 / `PASSWORD_CHANGE_REQUIRED` until `POST /auth/complete-first-login` succeeds;
- completing first login rotates the session and revokes the temporary-login session;
- username changes and emergency PIN resets revoke existing sessions;
- deleting an employee is a soft delete that preserves historical warehouse/payroll data.

The browser manager UI does not expose FastAPI bearer credentials to JavaScript. It authenticates through the Next.js `/web-auth/*` BFF routes and sends state-changing calls through the CSRF-protected `/web-api/*` proxy.

## Catalog, locations and inventory

```text
GET  /locations/parse/{location}
GET  /inventory/product/{asin}
GET  /inventory/location/{location}
POST /inventory/receive
POST /inventory/move
```

Operational inventory routes also expose alerts, cycle-count escalation and fulfillment-orderability information.

## Orders and picking

Core task routes:

```text
POST /orders
POST /orders/{order_id}/allocate
POST /orders/{order_id}/cancel
GET  /tasks/{task_id}
POST /tasks/{task_id}/scan
POST /tasks/{task_id}/sync
```

Dispatch/operations routes:

```text
GET  /ops/dispatch/workers
POST /ops/dispatch/tasks/{task_id}/broadcast
GET  /ops/dispatch/me/offers
POST /ops/dispatch/tasks/{task_id}/claim
POST /ops/dispatch/tasks/{task_id}/reject
POST /ops/dispatch/tasks/{task_id}/assign
POST /ops/tasks/{task_id}/handover
POST /ops/tasks/{task_id}/optimize-route
```

Important invariant: claim ownership is server-side and atomic. One picker cannot own two active pick orders.

## Pick exceptions and bags

```text
POST /ops/tasks/{task_id}/skip
POST /ops/tasks/{task_id}/damaged
POST /ops/tasks/{task_id}/bags
POST /ops/tasks/{task_id}/finish-picking
GET  /ops/orders/{order_id}/summary
GET  /ops/orders/search
```

Order search supports combinations of:

- order ID / external reference;
- full SPOO or SPOO suffix;
- picker username;
- time window.

## Worker operational state

```text
GET  /ops/me/state
POST /ops/me/state
```

Operational state controls dispatch eligibility. Picking is blocked while the worker is in a non-picking activity such as break, receiving, stow, unpack, cycle count or replenishment.

## Shift time, rota, leave and overtime

Direct shift clock endpoints:

```text
POST /ops/shifts/clock-in
POST /ops/shifts/clock-out
```

Planning endpoints:

```text
POST /ops/shifts/templates
GET  /ops/shifts/templates
POST /ops/shifts/assignments
GET  /ops/shifts/roster
POST /ops/shifts/clock-in/auto
POST /ops/shifts/clock-out/auto

POST /ops/breaks/start
POST /ops/breaks/end

POST /ops/leave
POST /ops/leave/{request_id}/review

POST /ops/overtime
POST /ops/overtime/{request_id}/review
```

Automatic time calculation includes:

- late after grace;
- worked minutes;
- early leave;
- overtime.

## Workforce / People & Payroll

```text
GET   /admin/employees
POST  /admin/employees
GET   /admin/employees/{user_id}
PATCH /admin/employees/{user_id}
DELETE /admin/employees/{user_id}

GET   /admin/usernames/{username}/availability
PATCH /admin/employees/{user_id}/account
POST  /admin/employees/{user_id}/set-pin
POST  /admin/employees/{user_id}/promote
POST  /admin/employees/{user_id}/attendance
POST  /admin/employees/{user_id}/performance-events
POST  /admin/employees/{user_id}/pay-adjustments
GET   /admin/employees/{user_id}/payroll-preview

GET   /admin/password-resets
POST  /admin/password-resets/{reset_id}/issue-temporary-password
```

Warehouse promotion ladder:

```text
PICKER
→ SENIOR_PICKER
→ QUALITY
→ QUALITY_LEADER
→ TEAM_LEADER
→ SUPERVISOR
```

`ADMIN` is outside the warehouse promotion ladder.

## Permission scopes and audit

```text
GET /ops/permissions/me
PUT /ops/permissions/roles/{role}
PUT /ops/permissions/users/{user_id}
GET /ops/audit
```

Role/user grants can extend or restrict default role permissions.

## Payroll policy

```text
GET /ops/payroll-policy/{user_id}
PUT /ops/payroll-policy/{user_id}
```

Performance metrics never directly change salary. Attendance deductions are applied only when an explicit payroll policy enables them.

## Fulfillment availability controls

```text
GET  /ops/availability/holds
POST /ops/availability/holds
POST /ops/availability/holds/{hold_id}/resume
GET  /ops/availability/holds/{hold_id}/impact
GET  /ops/catalog/{product_id}/orderability
```

Supported hold scopes:

```text
SITE
DOMAIN
ZONE
AISLE
BIN
SKU
```

Normal holds affect new orderability/allocation. `hard_stop=true` also blocks affected active pick scans.

## Replenishment

Legacy/read queue:

```text
GET /ops/replenishment
```

Executable v0.4 workflow:

```text
GET  /ops/replenishment/queue
POST /ops/replenishment/generate
POST /ops/replenishment/{task_id}/assign
POST /ops/replenishment/{task_id}/claim
POST /ops/replenishment/{task_id}/source
POST /ops/replenishment/{task_id}/item
POST /ops/replenishment/{task_id}/destination
POST /ops/replenishment/{task_id}/complete
POST /ops/replenishment/{task_id}/cancel
```

The completion event is idempotent and moves inventory through the normal inventory ledger.

## Receiving and stow

```text
POST /ops/shipments
GET  /ops/shipments
GET  /ops/shipments/lookup?code=4ZOXV48Q
GET  /ops/shipments/{shipment_id}
POST /ops/shipments/{shipment_id}/dock-check-in
POST /ops/shipments/{shipment_id}/open
POST /ops/shipments/{shipment_id}/receive
POST /ops/shipments/{shipment_id}/direct-stow
POST /ops/shipments/{shipment_id}/adhoc-stow  # backward-compatible alias
POST /ops/shipments/{shipment_id}/leave
POST /ops/shipments/{shipment_id}/issues
POST /ops/shipments/{shipment_id}/issues/{issue_id}/resolve
POST /ops/shipments/{shipment_id}/manager-close-receive
POST /ops/shipments/{shipment_id}/complete-receive

GET  /ops/stow/{task_id}/recommendations
POST /ops/stow/{task_id}/complete
```

Shipment list, lookup, reading, joining, leaving and issue reporting require an
active authenticated warehouse session, not `operations.manage`. Creation,
issue resolution and partial receiving closure require `operations.manage`.
HAZ/HRV receiving requires the relevant qualification.

Creation accepts optional `label` (blank generates a code), `supplier_name`,
`purchase_order_ref`, `order_date`, `delivery_from`, `delivery_to`,
`shipping_address`, `notes`, `storage_domain`, `shipment_type` and `lines`.
Each line accepts `product_id` as ID, SKU/ASIN or barcode, `expected_qty`,
`lot_code` and `expires_on`. Codes use 3–48 uppercase ASCII letters, digits,
`-`, `.`, `_` or `/`.

`open` records `opening_temperature_c` on first opening. Joining an already
opened shipment may omit the temperature. Each worker has one open session;
rejoining on another device rebinds the session to that device. `leave` pauses
only the caller's session and preserves the shipment.

`direct-stow` accepts `event_id`, `product_id`, `destination_location_id`, `qty`,
optional `lot_code`, `expires_on` and `reason`. A reason is required only for
unplanned/excess stock. The old `adhoc-stow` path remains supported. Receipt
and direct-stow events reject payload changes, including expiry and lot.

Issue requests carry `event_id`, optional `product_id`, `issue_type`, `qty`,
`notes`, optional `lot_code` and `expires_on`. Types: `DAMAGED`, `EXPIRED`,
`WRONG_ITEM`, `MISSING`, `TEMPERATURE`, `PACKAGING`, `OTHER`. Item-specific
issues require a product and positive quantity. `DAMAGED`/`EXPIRED` require
an open receiving session and record rejected incoming stock in `DMG`;
other types are incidents without inventory effects. Retrying identical
issue events returns `duplicate: true`. Resolving requires `resolution` text
and records the manager/time without changing stock.

Shipment payloads include `barcode_value`, supplier/PO/date metadata, enriched
item `title`/`asin`/`barcode`, `issues`, `open_issues` and `receiving_users`.
Regular `complete-receive` rejects remaining expected units with
`PARTIAL_RECEIPT_REQUIRES_MANAGER`; manager closure records the shortfall.

## Topology, capacity and optimization

```text
POST /ops/topology/nodes
POST /ops/topology/edges
GET  /ops/topology

GET /ops/locations/{location_id}/capacity
PUT /ops/locations/{location_id}/operational-profile

GET  /ops/analytics/heatmap
GET  /ops/expiry-risk
POST /ops/simulation/order
GET  /ops/slotting/suggestions
```

The optimizer can use configured graph distances, one-way paths and congestion factors. When detailed topology is absent it falls back to location heuristics.

## Incidents and guard rules

```text
GET  /ops/incidents
PUT  /ops/guards/{domain}/{rule_type}
POST /ops/guards/evaluate
POST /ops/inventory/alerts/{alert_id}/create-cycle-count
```

Guard rules can automate operational availability decisions such as pausing a domain when no qualified handler is clocked in.

## Performance

```text
GET /ops/performance
```

Current factual metrics include order/unit/bag counts, late-SLAM count/rate and average pick time.

## Technical downtime

```text
POST /tasks/{task_id}/downtime/start
POST /tasks/{task_id}/downtime/{segment_id}/stop
```

Downtime segments are used to separate technical delay from accountable associate time.

## System diagnostics / eventing

```text
GET /admin/system/health
```

The authenticated diagnostic payload includes transactional-outbox counts, telemetry state, OTLP-export configuration and incident-webhook configuration.

Authoritative business changes can enqueue integration events in PostgreSQL in the same transaction. The background dispatcher retries delivery independently; failure of telemetry/webhook delivery does not roll back committed warehouse state.

## API evolution principles

Future API hardening should continue toward:

- OpenAPI-generated Android client models;
- request/trace IDs;
- rate limits;
- short-lived browser sessions;
- stronger scope enforcement on every sensitive endpoint;
- transactional outbox/event publication;
- explicit API versioning where backward compatibility requires it.
