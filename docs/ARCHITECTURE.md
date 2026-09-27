# FulfillOS architecture — v0.4

## 1. System boundary

FulfillOS is a micro-fulfillment execution platform with five cooperating layers:

```text
┌──────────────────────────────────────────────────────────────┐
│ Governance                                                   │
│ People • ranks • permissions • audit • payroll policy        │
├──────────────────────────────────────────────────────────────┤
│ Control                                                      │
│ Dispatch • holds • incidents • heatmap • route simulation    │
├──────────────────────────────────────────────────────────────┤
│ Execution                                                    │
│ Receive • Unpack • BOH • Replenish • Pick • Stow • Recovery  │
├──────────────────────────────────────────────────────────────┤
│ Digital inventory                                           │
│ Catalog • barcodes • locations • ledger • reservations       │
├──────────────────────────────────────────────────────────────┤
│ Physical site                                                │
│ shelves • racks • drawers • chiller • freezer • staging      │
└──────────────────────────────────────────────────────────────┘
```

Android and web are execution/control clients. Neither is the source of truth.

## 2. Runtime topology

```text
Android PDA ───────┐
                   │ HTTPS
Next.js Web ───────┼────► FastAPI
                   │         │
                   │         ├────► PostgreSQL / Neon
                   │         │       authoritative state
                   │         │
                   │         └────► MongoDB Atlas
                   │                 best-effort telemetry
                   │
                   └────► server-authoritative execution
```

## 3. Authoritative data model

PostgreSQL owns:

- users, devices and sessions;
- employee/workforce data;
- ranks, promotion history and payroll policy;
- shift templates, assignments, breaks, leave and overtime requests;
- product/barcode/location master;
- inventory balances;
- immutable movement evidence;
- orders/order lines;
- pick tasks/items;
- pick ownership leases;
- dispatch offers;
- fulfillment holds;
- bags/SPOO;
- pick exceptions;
- replenishment tasks/events;
- shipments/receiving/stow;
- operational incidents;
- guard rules;
- audit events.

MongoDB Atlas is not allowed to become authoritative for stock, orders, payroll or task ownership.

## 4. Bounded domains

### Identity and governance

Responsibilities:

- authentication;
- trusted device session;
- role + permission scopes;
- promotion history;
- admin audit;
- password recovery.

Operational warehouse rank ladder:

```text
PICKER
→ SENIOR_PICKER
→ QUALITY
→ QUALITY_LEADER
→ TEAM_LEADER
→ SUPERVISOR
```

`ADMIN` is a technical governance role outside the warehouse promotion ladder.

### Workforce planning

Responsibilities:

- employee profile;
- shift templates;
- timezone-aware rota;
- clock in/out;
- break sessions;
- leave;
- overtime;
- payroll preview;
- explicit attendance deduction policy.

### Catalog

Responsibilities:

- catalog product;
- barcode mappings;
- title/metadata;
- temperature requirement;
- HAZ/HRV classification;
- expiry/lot context.

### Location master

A location record stores operational facts rather than forcing the system to infer everything from its identifier:

- site/floor;
- fixture;
- aisle/level/slot;
- temperature;
- handling class;
- pickable/stowable/sellable;
- topology-node link;
- optional capacity;
- average pick-time profile.

### Inventory ledger

Inventory state is changed only through explicit movement commands.

```text
(source, product)
   └── movement(event_id, qty, reason, actor, device)
         └──► (destination, product)
```

Duplicate event IDs return the existing committed effect instead of moving stock twice.

### Orders and picking

The order/task model owns:

- allocation;
- reservations;
- task sequence;
- ownership;
- picking state;
- cancellation/recovery;
- bags;
- completion.

A picker cannot own two active pick orders because the backend maintains an active pick lease.

### Dispatch

Dispatch uses:

- worker active flag;
- current runtime state;
- existing active pick lease;
- task-required qualifications;
- worker HAZ/HRV qualifications;
- optional allowed-domain profile;
- device/location telemetry.

Broadcast offers can be visible to multiple eligible workers, but claim is atomic and only one succeeds.

### Fulfillment availability

Availability control is separate from inventory.

```text
physical stock
  !=
fulfillable stock
```

A fulfillment hold filters stock from new orderability/allocation. It does not mutate `qty_on_hand`.

Scopes:

- SITE
- DOMAIN
- ZONE
- AISLE
- BIN
- SKU

Hard-stop mode additionally rejects pick execution in the blocked scope.

### Replenishment

Replenishment has an independent task lifecycle and is not mixed into order picking ownership.

It records:

- source;
- destination;
- product;
- planned qty;
- actual qty;
- worker ownership;
- scan evidence;
- event IDs;
- partial completion;
- cancellation/failure.

Inventory movement occurs only after source/item/destination validation.

### Receiving and stow

Shipment execution owns:

- dock state;
- storage domain;
- expected quantity;
- good/damaged/missing reconciliation;
- lot/expiry;
- inbound location;
- receiving session;
- target stow timer;
- generated stow tasks.

### Operations intelligence

Read/decision support includes:

- picker performance;
- heatmap;
- expiry risk;
- slotting suggestions;
- topology graph;
- route simulation;
- capacity snapshots;
- incident center;
- automatic guard evaluation.

Read models can suggest actions, but suggestions do not silently mutate stock or employee compensation.

## 5. Pick transaction boundary

A committed pick performs:

1. validate task ownership;
2. validate runtime/task state;
3. validate client event ID and sequence;
4. validate expected item/product/source;
5. enforce hard fulfillment stops;
6. validate inventory;
7. move inventory to pick tote;
8. update picked quantity;
9. persist scan evidence;
10. increment server version;
11. transition task/order if complete;
12. record late-SLAM event when the downtime-aware SLA is exceeded;
13. commit once.

The UI is updated from the authoritative snapshot after commit.

## 6. Replenishment transaction boundary

Completion performs:

1. validate worker ownership;
2. require source scan;
3. require item scan;
4. require destination scan;
5. validate product/location compatibility;
6. validate quantity;
7. idempotently move inventory;
8. persist replenishment event;
9. close or partially close the task;
10. optionally create remainder task;
11. release worker operational state.

## 7. Route optimization

v0.4 supports two levels:

### Baseline

- ambient/produce/HAZ/HRV first;
- chilled after warm;
- frozen last;
- aisle/slot heuristic.

### Configured topology

A site can define nodes/edges with:

- measured distance;
- one-way flag;
- congestion factor;
- domain/aisle context.

The route engine uses the graph when available and falls back to heuristics when detailed topology is absent.

## 8. Workforce decision boundary

Performance metrics are evidence, not automatic employment actions.

Examples:

- orders;
- units;
- bags;
- average pick time;
- late SLAM;
- attendance.

Promotion and compensation changes require explicit commands and audit evidence.

## 9. Schema evolution

v0.4 moves forward schema evolution to Alembic.

Startup behavior:

```text
existing pre-Alembic DB
  -> detect existing core tables
  -> stamp verified baseline
  -> upgrade to head

fresh DB
  -> create current metadata once
  -> stamp head
  -> future revisions via Alembic
```

PostgreSQL uses an advisory lock so two serverless cold starts do not race migrations.

## 10. Event publication roadmap

Future scalable event distribution should use the transactional outbox pattern:

```text
PostgreSQL transaction
  └─ outbox row
      └─ publisher
          └─ event bus
              ├─ live dashboard
              ├─ notifications
              ├─ analytics
              └─ audit/export
```

The database transaction remains the accounting source of truth.

## 11. Security model

Current principles:

- passwords stored as slow hashes;
- access + rotating refresh credential;
- device-bound sessions;
- release Android endpoint must be HTTPS;
- sensitive web/admin routes are permission-gated;
- stock mutations include actor/device/event context;
- promotion records include approver/reason/effective time;
- admin overrides should be auditable.

High-priority future hardening:

- HttpOnly/SameSite browser sessions;
- CSRF protection;
- verified email/SMS recovery;
- protected production signing key;
- broader sensitive-field audit coverage;
- retention/export controls for HR data.
