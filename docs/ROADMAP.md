# FulfillOS roadmap

_Status snapshot: 28 September 2026._

## P0 — reliability kernel — implemented

- location grammar and logical/special locations;
- catalog + barcode entities;
- inventory balance + movement ledger;
- idempotent stock movement;
- deterministic allocation;
- pick task server version + client sequence;
- durable-event protocol;
- mid-pick cancellation recovery;
- device-bound session/refresh model;
- downtime-aware SLA accounting;
- supervisor dashboard;
- critical-invariant tests.

## P1 — operational depth — substantially implemented

Implemented:

- Receive v3 core: shipment → dock/open → receive → discrepancy → stow;
- Unpack backend with temperature-aware temporary totes;
- BOH move and destination compatibility;
- damage/DMG movement;
- cycle count backend;
- skip / short / damaged pick exceptions;
- repeated-short alerts;
- replenishment candidate creation;
- HAZ/HRV qualifications;
- pack/rack/stage/handoff backend;
- multi-bag SPOO;
- Order Explorer;
- fulfillment holds;
- cold-chain timers;
- expiry/lot awareness;
- stow capacity checks.

Remaining:

- richer disposition lifecycle after damage;
- polished barcode/ASIN management UI;
- full SPECIAL-bin site policy;
- full handheld UI for several non-pick workflows.

## P2 — Android production client — partially implemented

Implemented:

- Kotlin + Jetpack Compose;
- durable local pick-event journal;
- session/task recovery;
- WorkManager retry infrastructure;
- connectivity handling;
- production endpoint safety;
- broadcast offers;
- atomic accept;
- pick scanning;
- skip / short / damaged;
- multi-bag SPOO;
- completion summary;
- worker state integration;
- inventory/barcode tools;
- screen models/routing for additional operational modules.

Still required:

- complete production-grade Receive screen;
- complete Unpack screen;
- complete BOH Move screen;
- complete Damage disposition screen;
- complete Cycle Count screen;
- complete Recovery screen;
- complete Replenishment handheld flow;
- industrial scanner intent/profile adapters;
- camera fallback scanner;
- stronger foreground-task UX;
- localization/RTL polish;
- device-health and recovery diagnostics.

## P3 — production backend / governance — partially implemented

Implemented:

- PostgreSQL / Neon production DB;
- Alembic baseline;
- safe startup migration runner;
- PostgreSQL advisory migration lock;
- role/user permission grants;
- admin audit-event model;
- worker runtime state;
- active pick leases;
- operational incidents;
- guard rules;
- workforce profiles;
- rank promotion history;
- rota/shift templates;
- break/leave/overtime workflows;
- explicit payroll attendance policy;
- production Vercel deployment.

Still required:

- transactional outbox;
- event bus / live projection distribution;
- SSE/WebSocket live control tower;
- OpenTelemetry tracing;
- structured production metrics;
- backup/restore drills;
- disaster recovery;
- stronger multi-site tenancy/isolation model;
- complete audit coverage for every sensitive employee/payroll mutation;
- short-lived browser sessions + CSRF protection.

## P4 — optimization — baseline implemented, calibration remains

Implemented:

- warm/ambient before chilled before frozen;
- topology nodes/edges;
- route-distance engine;
- one-way edge support;
- congestion-factor support;
- heuristic fallback;
- FEFO-aware selection;
- demand/velocity slotting suggestions;
- capacity profiles;
- warehouse heatmap;
- expiry risk;
- order-route simulation.

Still required:

- measured site walk distances;
- real one-way path map;
- live congestion calibration;
- cube/volume-aware capacity;
- demand forecasting;
- labor planning;
- anomaly detection;
- richer replenishment priority/SLA;
- optional wave/batch picking if site operations adopt it.

## P5 — workforce maturity

Implemented foundation:

- employee onboarding;
- contact/job/payroll data;
- attendance;
- overtime;
- payroll preview;
- password-reset queue;
- shift templates;
- rota assignments;
- breaks;
- leave requests;
- overtime requests;
- permission scopes;
- promotion history.

Warehouse rank ladder:

```text
PICKER
→ SENIOR_PICKER
→ QUALITY
→ QUALITY_LEADER
→ TEAM_LEADER
→ SUPERVISOR
```

Remaining:

- verified email/SMS self-service password reset;
- HR field retention/export/delete policy;
- broader sensitive-data audit;
- richer employee self-service;
- configurable performance-review periods;
- promotion eligibility recommendations with explicit human approval;
- salary-policy/version history;
- statutory payroll/tax rules only if required by the deployment jurisdiction.

## P6 — hardware and facility integrations

Planned:

- production signing / Play App Signing;
- MDM/kiosk enrollment;
- industrial scanner profiles;
- NFC/badge sign-in;
- label/printer workflows;
- environmental/cold-chain sensors;
- shelf/rack indicators;
- electronic shelf labels.

## v0.3 milestone — completed

- one-picker/one-order hard lease;
- atomic broadcast claim;
- supervisor assignment;
- operational-state dispatch gating;
- Order Explorer;
- multi-bag SPOO;
- fulfillment holds;
- receiving/stow core;
- automatic shift time calculations;
- performance dashboard;
- topology/route optimization baseline.

## v0.4 milestone — completed

- Alembic migration framework;
- safe pre-Alembic production baseline;
- migration advisory lock;
- executable replenishment;
- proactive low-stock replenishment candidates;
- shift templates + rota;
- automatic scheduled clock in/out;
- break sessions;
- leave/overtime request workflows;
- permission scopes;
- admin audit events;
- warehouse rank ladder;
- explicit audited promotion workflow;
- promotion history in People & Payroll;
- Team Leader operations access;
- Quality/Quality Leader scoped permissions;
- Android v0.4 routing/model integration;
- deployment health version fixed to v0.4;
- APK artifact names derived from Gradle version.

## Immediate next engineering sequence

1. finish non-pick Android operational screens;
2. industrial scanner + camera fallback;
3. production app signing;
4. browser session/cookie hardening;
5. full sensitive-change audit coverage;
6. verified self-service password recovery;
7. transactional outbox + live event projections;
8. observability/incident notification;
9. measured warehouse topology calibration;
10. replenishment SLA/priority UX.
