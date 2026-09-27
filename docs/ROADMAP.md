# Build roadmap

## P0 — reliability kernel — implemented in this foundation

- location grammar and special/logical bins;
- catalog + barcode entities;
- inventory balance + immutable movement records;
- idempotent stock movement;
- deterministic order allocation;
- pick tasks with server version and client sequence;
- durable-event protocol contract;
- mid-pick cancellation recovery;
- device-bound session/refresh model;
- downtime-aware SLA accounting;
- supervisor dashboard;
- automated tests for the critical invariants.

## P1 — operational depth — substantially implemented in v0.3

- **implemented core:** Receive v3 shipment → dock/open → receive → discrepancy → stow flow;
- **implemented backend:** Unpack sessions with ambient/chilled/frozen tote enforcement;
- **implemented backend:** BOH move and destination compatibility validation; Bulk move UI remains;
- **implemented backend:** damage reasons and DMG movement; richer disposition lifecycle remains;
- **implemented backend:** cycle count and adjustment application; supervisor approval layer remains;
- **implemented:** separate skip / short / damaged workflows with repeated-short alerting and replenishment candidates;
- **implemented backend:** pack/rack, stage, handoff and delivery completion; PDA screens remain;
- **implemented:** HAZ and HRV worker qualifications used by receiving and dispatch;
- barcode-ASIN management UI;
- explicit `SPECIAL` bin policy once site semantics are known.

## P2 — Android production client

- Room database for session snapshot, tasks and pending event journal;
- hardware barcode scanner intent/profile adapters;
- camera fallback scanner;
- WorkManager sync worker;
- connectivity state machine;
- secure refresh token storage with Android Keystore;
- foreground task service while actively picking;
- boot/restart recovery;
- device health telemetry;
- Compose screens for pick, inventory viewer, receive, unpack, BOH and metrics;
- RTL-ready localization.

## P3 — distributed production backend

- PostgreSQL migrations with Alembic;
- row-level concurrency strategy and stronger serializable invariants where required;
- transactional outbox;
- NATS JetStream event distribution;
- Redis hot projections/locks only where justified;
- WebSocket/SSE live control tower;
- observability: OpenTelemetry traces, structured logs and metrics;
- backup/restore and disaster recovery;
- multi-site partitioning.

## P4 — optimization

- **implemented baseline:** warm → chilled → frozen route sequencing;
- physical site graph and measured walking costs;
- route optimizer with cold-chain ordering constraints;
- **implemented baseline:** demand/velocity slotting recommendations; cube/capacity scoring remains;
- demand forecasting integrations;
- wave/batch picking where site operations support it;
- labor planning without attributing infrastructure downtime to associates;
- anomaly detection for repeated scans, impossible movements and inventory drift.

## P5 — hardware and facility integrations

- environmental sensors and cold-chain alert ingestion;
- electronic shelf labels;
- industrial printer/label workflows;
- MDM/kiosk enrollment;
- NFC/badge sign-in;
- rack/stage indicators where hardware supports them.

## v0.3 completed cross-cutting work

- one-picker/one-order hard lease;
- broadcast first-winner dispatch and supervisor assignment;
- operational work-state gating;
- Order Explorer with SPOO and picker search;
- multi-bag completion;
- fulfillment-area pause/resume without falsifying inventory;
- automatic shift time calculations and explicit payroll policies;
- receiving/stow/cold-chain timers;
- fast-mover suggestions;
- Android PDA support for broadcast offers, skip/short/damage and bag close.
