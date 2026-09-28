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

## P2 — Android production client — core workflows implemented

Implemented:

- Kotlin + Jetpack Compose;
- durable local pick/operation event journals;
- session/task recovery;
- WorkManager retry infrastructure;
- connectivity handling;
- production endpoint safety;
- 5-second PDA presence heartbeat;
- 3-second automatic Waiting Order / active-task polling;
- first-login personal PIN setup gate;
- broadcast offers and atomic accept;
- picking, skip / short / damaged, multi-bag SPOO and completion summary;
- inventory/barcode viewer;
- production Compose screens for Receive/Stow, Unpack, BOH Move, Damage, Cycle Count, Recovery and Replenishment;
- generic/Zebra-Honeywell-Datalogic broadcast scanner normalization;
- CameraX + on-device ML Kit barcode fallback;
- shared scanner pipeline for hardware/camera/manual test input.

Still required:

- validate scanner profiles on the exact physical PDA fleet;
- stronger foreground-task/kiosk UX;
- localization/RTL polish;
- real-site acceptance tests for every operation;
- production signing / Play App Signing.

## P3 — production backend / governance — core platform implemented

Implemented:

- PostgreSQL / Neon production DB;
- Alembic baseline and v0.5 schema revisions;
- safe startup migration runner + PostgreSQL advisory lock;
- role/user permission grants;
- broad sensitive-change audit coverage;
- worker runtime state and active pick leases;
- operational incidents and guard rules;
- workforce profiles, rank history, rota, leave, overtime and payroll policy;
- forced first-login PIN lifecycle, unique username management and safe soft delete;
- Next.js BFF with HttpOnly/SameSite access+refresh cookies and CSRF validation;
- transactional outbox with retry/backoff and PostgreSQL SKIP LOCKED;
- Mongo event-stream sink and optional incident webhook;
- OpenTelemetry FastAPI/SQLAlchemy instrumentation;
- structured HTTP logs, request/error counters and latency histograms;
- production Vercel deployment.

Still required:

- SSE/WebSocket consumers/live projections on top of the outbox;
- backup/restore and disaster-recovery drills;
- stronger multi-site tenancy/isolation model;
- privacy/retention/export policy;
- production alert destination configuration and runbooks.

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

- verified email/SMS self-service PIN reset;
- HR field retention/export/delete policy;
- richer employee self-service;
- configurable performance-review periods;
- promotion eligibility recommendations with explicit human approval;
- salary-policy/version history;
- statutory payroll/tax rules only if required by the deployment jurisdiction.

## P6 — hardware and facility integrations

Planned / rollout work:

- production signing / Play App Signing;
- MDM/kiosk enrollment;
- physical-site industrial scanner profile validation;
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

## v0.5 milestone — implemented on current release branch

- numeric employee PIN policy (6–10 digits) with six-digit random generation;
- mandatory first-login personal PIN setup;
- username uniqueness/change and session revocation;
- emergency manager PIN reset;
- safe user deactivation preserving operational history;
- fresh-PDA presence requirement for dispatch;
- 5-second heartbeat and 3-second Waiting Order refresh;
- reorganized web navigation and Quick Actions;
- HttpOnly/SameSite BFF browser session with CSRF;
- full non-pick PDA operation screens;
- industrial scanner adapters plus CameraX/ML Kit fallback;
- broader sensitive-change audit;
- transactional outbox and retrying event distribution;
- OpenTelemetry + structured request metrics/logging;
- optional incident webhook.

## Immediate next engineering sequence

1. keep v0.5 CI green and deploy the merged release;
2. production signing / Play App Signing;
3. verified self-service email/SMS PIN recovery;
4. physical PDA/scanner acceptance tests and site profiles;
5. SSE/WebSocket live projections using outbox events;
6. measured warehouse topology calibration;
7. backup/restore + rollback drills;
8. privacy/retention/export controls;
9. multi-site/tenant hardening;
10. replenishment SLA/priority calibration from real demand data.
