# Architecture

## 1. System boundary

FulfillOS is a micro-fulfillment execution platform with four layers:

```text
┌─────────────────────────────────────────────────────────────┐
│ Control                                                     │
│ Supervisor dashboard • SLA • device health • audit • alerts │
├─────────────────────────────────────────────────────────────┤
│ Execution                                                   │
│ Receive • Unpack • BOH Move • Pick • Stage • Handoff        │
├─────────────────────────────────────────────────────────────┤
│ Digital inventory                                           │
│ Catalog • barcode mapping • ledger • locations • states      │
├─────────────────────────────────────────────────────────────┤
│ Physical site                                               │
│ shelves • drawers • hanging • baskets • chiller • freezer   │
└─────────────────────────────────────────────────────────────┘
```

The Android PDA is not the source of truth. It is an execution client over a durable server-side task and inventory model.

## 2. Bounded domains

### Catalog

- product id / ASIN-like catalog key;
- one-to-many physical barcodes;
- title and image references;
- temperature requirement;
- handling/security classification.

### Location master

- physical and logical locations;
- fixture type separate from hazard/security classification;
- temperature class;
- pickable / stowable / sellable attributes;
- human visual aids such as level color.

### Inventory ledger

A balance is a materialized view of append-only movements.

```text
(source, product) -- movement(event_id, qty) --> (destination, product)
```

A duplicate `event_id` returns the original result instead of changing stock again.

### Orders

Customer demand and line quantities. Order status is not inferred from the UI. It is persisted and versioned.

### Task orchestration

Converts allocated order lines into route-ordered work. The current allocator is deterministic and intentionally simple. A graph optimizer can replace its sorting policy without changing pick semantics.

### Device and identity

User and PDA are distinct entities. A trusted device receives refresh credentials that survive application process death/reboot when stored by the Android client in hardware-backed storage.

### SLA

Elapsed wall time and accountable associate-active time are different quantities. Downtime segments can be recorded as:

- `NETWORK_OFFLINE`
- `BACKEND_WAIT`
- `DEVICE_RECOVERY`
- `SYSTEM_EXCEPTION`

Only policy-approved segments are excluded from associate active time.

## 3. Source of truth

The authoritative state is the relational transaction boundary in the backend:

- inventory balances and movement log;
- order status;
- pick task status/version;
- scan-event acknowledgement;
- downtime segments.

Redis may cache views, and NATS may distribute committed events, but neither is the accounting source of truth.

## 4. Transaction model for a pick

One committed transaction performs:

1. verify task ownership and state;
2. verify next client sequence;
3. verify task item, product and source location;
4. verify inventory is available;
5. write an idempotent movement into the order pick tote;
6. increment task-item and order-line picked quantity;
7. write the acknowledged scan event;
8. increment server version;
9. possibly transition task/order to `PICKED`;
10. commit once.

No UI counter is allowed to become authoritative before step 10.

## 5. Event publication

Production evolution:

```text
PostgreSQL transaction
  └─ outbox row
      └─ publisher
          └─ NATS JetStream
              ├─ dashboard projection
              ├─ notifications
              ├─ analytics
              └─ audit export
```

The transactional outbox avoids the classic failure where the database commits but message publication does not, or vice versa.

## 6. Security model

- passwords are never stored on the PDA;
- server password hashes use a slow KDF;
- short-lived access token + rotating refresh token;
- refresh token is bound to a device id;
- Android stores refresh material using hardware-backed Keystore where available;
- HAZ/HRV workflows can add role/skill gates;
- all stock mutations include actor, device and event id;
- supervisor overrides require a reason and produce audit records.

The demo backend uses PBKDF2 from the Python standard library. A production deployment should use an organization-approved password/KMS/authentication solution and centralized identity.
