# FulfillOS

FulfillOS is a clean-room micro-fulfillment / dark-store execution platform built from observed warehouse workflows and first-principles system design. It does **not** copy proprietary source code, private endpoints, credentials, internal brand assets, or vendor-specific implementations.

The project is reliability-first: PostgreSQL owns transactional truth, client actions are replay-safe, Android can recover from network/process/device failure, inventory mutations are idempotent, picker/order ownership is enforced server-side, and workforce/payroll decisions remain explicit and auditable.

## Current status

_Status snapshot: 28 September 2026._

The open [PR #30](https://github.com/obieda-hussien/sass/pull/30) adds direct
employee management, PDA activity and icon-first navigation. Its inbound
follow-up now binds a multi-bag SPOO scan to the complete order manifest,
records receiving-zone temperature and unplanned-stock reasons, and gives
managers item-level shortfall and putaway progress with a partial-close action.

| Component | Current state |
| --- | --- |
| FulfillOS release | **v0.5.1** |
| Android | Kotlin + Jetpack Compose, versionCode **7**, minSdk 26, targetSdk 36 |
| API | FastAPI + SQLAlchemy |
| Primary database | PostgreSQL / Neon |
| Schema management | **Alembic** with safe pre-Alembic baseline + startup migration runner |
| Telemetry/read models | MongoDB Atlas, non-authoritative |
| Web | Next.js Control Tower + Operations + People & Payroll |
| Hosting | Vercel Services |
| CI/CD | GitHub Actions |
| Production | https://fulfillos-nine.vercel.app |
| Production API | https://fulfillos-nine.vercel.app/api |
| Release line | FulfillOS v0.5 UX/realtime/security hardening |

The latest `main` build/deploy checks are green. Production deployment validates `/api/health`, PostgreSQL connectivity, telemetry connectivity, the web root, and then builds production-connected Android APK artifacts.

## v0.5.1 scanner & presence patch

v0.5.1 tightens the PDA experience:

- the Android app publishes an immediate foreground heartbeat on resume and an explicit OFFLINE/background heartbeat on pause;
- stale activity such as `WAITING_FOR_ORDER` is never rendered as live when the PDA heartbeat is offline/stale;
- the Operations Console refreshes picker presence every 3 seconds;
- camera scanning is context-driven: inventory search, accepted/direct-assigned pick work, bin/item transitions, SPOO, unpack, BOH, damage, cycle count, recovery, receive/stow and replenishment request the camera automatically when the next step needs a scan;
- industrial scanner broadcasts and the camera still feed the same ScanBus and server-side validation.

Broadcast offers do **not** cover the screen with a camera before the worker accepts them; the camera opens immediately after acceptance when the first physical scan is actually required.

## What v0.5 contains

### Warehouse execution

- transactional inventory ledger;
- physical/logical location master;
- deterministic allocation with FEFO-aware stock selection where lot expiry data exists;
- topology-aware route optimization with warm/ambient → chilled → frozen ordering;
- one picker → one active order database lease;
- broadcast order offers with atomic first-winner claim;
- supervisor/team-leader direct assignment to eligible workers;
- operational-state gating during break, receiving, stow, unpack, cycle count, replenishment, training and other non-picking work;
- HAZ/HRV qualification checks;
- picker domain restrictions;
- skip / short / damaged-item flows;
- repeated-short inventory alerts and replenishment candidates;
- multi-bag SPOO close and order completion summary;
- order search by order ID, external reference, picker, full SPOO/suffix and time window;
- fulfillment holds at SITE / DOMAIN / ZONE / AISLE / BIN / SKU level;
- separate physical, fulfillable and blocked stock;
- emergency hard-stop mode for affected picking;
- receive → discrepancy reconciliation → stow workflow;
- lot/expiry capture;
- cold-chain target-stow timers;
- bin-capacity-aware stow recommendations;
- warehouse heatmap, expiry-risk reporting, route simulation and operational incidents.

### Replenishment

Replenishment is now an executable workflow rather than only a recommendation:

```text
READY / ASSIGNED
   ↓
CLAIMED
   ↓
scan source bin
   ↓
scan item
   ↓
scan destination bin
   ↓
confirm actual quantity
   ↓
COMPLETED / PARTIAL
```

The flow is server-owned, idempotent and inventory-backed. A partial move can create a remainder task. The system can also generate proactive low-pick-face candidates from reserve stock.

### Workforce, rota and payroll

- employee profiles with contact/job/payroll metadata;
- shift templates with timezone, start/end, break and grace policy;
- dated rota assignments;
- automatic scheduled-shift clock-in/out;
- late-after-grace calculation;
- early-leave calculation;
- actual worked minutes;
- overtime calculation;
- break sessions;
- leave requests + review;
- overtime requests + review;
- explicit payroll attendance-deduction policy;
- approved pay adjustments;
- payroll preview;
- password-reset request queue;
- numeric employee PIN policy: 6–10 digits;
- generated onboarding/reset PINs are exactly 6 random digits;
- mandatory personal-PIN change on first PDA login;
- emergency manager PIN reset with session revocation;
- unique username changes and safe user deactivation;
- permission grants and admin audit events.

Operational performance metrics do **not** automatically change employment status, rank or salary.

## Warehouse rank ladder

The operational promotion ladder is:

```text
PICKER
  ↓
SENIOR_PICKER
  ↓
QUALITY
  ↓
QUALITY_LEADER
  ↓
TEAM_LEADER
  ↓
SUPERVISOR
```

`ADMIN` is a technical/governance role outside the normal warehouse promotion ladder. `RECEIVER` and `INVENTORY` remain operational specializations rather than promotion levels.

A promotion records:

- previous rank;
- new rank;
- reason;
- approver;
- effective timestamp;
- old base salary;
- new base salary.

Promotions cannot be performed through the generic employee PATCH path, so rank changes cannot bypass promotion history. A promotion may keep salary unchanged or explicitly increase it; the system does not invent a salary increase automatically.

## Permission model

The permission model includes role scopes plus explicit user/role overrides.

Examples include:

- `operations.read`
- `operations.manage`
- `employees.read`
- `employees.write`
- `quality.read`
- `quality.inspect`
- `quality.manage`
- `attendance.approve`
- `shifts.manage`
- `replenishment.execute`
- `replenishment.manage`
- `payroll.read`
- `payroll.adjust`
- `promotions.manage`
- `permissions.manage`
- `audit.read`

Default role scopes are defined in the backend and can be overridden through explicit grants.

## Web surfaces

### Control Tower — `/`

Operational overview, active associates, task pipeline, recovery visibility and site state.

### Operations — `/operations`

- live picker availability;
- worker state / active-task visibility;
- manual dispatch;
- domain/zone fulfillment holds;
- Order Explorer;
- SPOO visibility;
- performance metrics;
- inbound shipment/stow status;
- demand/slotting suggestions.

Team Leader, Supervisor and Admin can access the operations control surface according to permissions.

### People & Payroll — `/people`

- employee onboarding with duplicate-username checks;
- numeric temporary/custom PIN creation;
- profile/contact/job/payroll data;
- username changes with session revocation;
- emergency PIN resets;
- safe user deactivation while preserving historical orders/payroll/audit;
- attendance/overtime;
- shift templates and rota assignments;
- payroll preview;
- pay adjustments;
- password resets;
- rank promotion workflow;
- promotion history.

### Admin & Audit — `/system`

- authenticated system-health view;
- PostgreSQL outbox pending/published/failed state;
- OTLP and incident-webhook configuration visibility;
- effective permission inspection;
- role-level allow/deny overrides;
- user-level allow/deny overrides;
- sensitive-change audit trail with entity filters.

### Browser session security

The manager web console no longer stores bearer tokens in `localStorage`. Next.js acts as a BFF:

- access and refresh credentials are stored in `HttpOnly`, `SameSite=Strict` cookies;
- state-changing browser requests require an `X-CSRF-Token` matching the CSRF cookie;
- the browser calls the authenticated `/web-api/*` proxy instead of reading bearer credentials;
- the BFF refreshes an expired access credential server-side;
- logout clears all web session cookies.

## Android PDA

The Android app targets the server-authoritative execution model and includes:

- trusted device login + refresh;
- mandatory first-login personal PIN change before warehouse tools unlock;
- 5-second PDA heartbeat with connectivity, battery, current task, activity and last-location context;
- automatic active-task / Waiting Order polling every 3 seconds while the PDA is online;
- durable pending-event journals and WorkManager retry infrastructure;
- offline/reconnect handling and active-task recovery;
- broadcast offer discovery with atomic first-winner acceptance;
- pick scanning plus skip / short / damaged flows;
- multi-bag SPOO close and order-completion summary;
- inventory/barcode tools;
- full Compose operational screens for Receive/Stow, Unpack, BOH Move, Damage, Cycle Count, Recovery and Replenishment;
- foreground industrial scanner adapters for generic FulfillOS profiles plus Zebra/DataWedge, Honeywell and Datalogic payloads;
- CameraX + on-device ML Kit barcode scanning as a camera fallback;
- a shared ScanBus so hardware, camera and manual test scans follow the same validation path.

Receive/Stow, BOH, Damage, Recovery and picking preserve server-side validation; durable local queues are used where the workflow is designed for retryable offline operation. Site-specific scanner profiles and physical warehouse validation still need real-device calibration before broad rollout.

### Production endpoint safety

Debug builds may use a development endpoint.

Release builds require:

```text
FULFILLOS_API_BASE_URL=https://...
```

and fail the build if the value is missing or non-HTTPS. Production APK artifact names are derived from Gradle `versionName` to prevent release-label drift.

Release APKs are currently internally installable and still use the debug signing configuration. A protected release key / Play App Signing flow is still required before store distribution.

## Core reliability invariants

1. PostgreSQL is authoritative for inventory, task, workforce and payroll state.
2. Every inventory-changing client event has a globally unique event ID.
3. Android persists retryable work before first transmission.
4. Retries are idempotent.
5. UI progress represents server-confirmed progress.
6. Task snapshots are versioned; client-sequence conflicts are rejected.
7. One picker can own at most one active pick order.
8. A pick order can have only one winning owner.
9. A cancelled partially picked order becomes explicit recovery work.
10. Physical stock and fulfillable stock are separate facts.
11. Fulfillment holds never falsify physical on-hand inventory.
12. Technical downtime is separated from accountable associate time.
13. Worker operational state gates dispatch.
14. Rank/pay changes require explicit auditable actions.
15. Production releases cannot silently target an emulator API URL.
16. A temporary employee PIN cannot access warehouse APIs until the employee sets a personal PIN.
17. A picker is dispatchable only while its PDA heartbeat is fresh; stale “ONLINE” devices cannot receive new work.
18. Sensitive workforce/payroll/account changes are audit events and are emitted through the transactional outbox.
19. External telemetry/incident delivery is retryable and cannot roll back an already committed warehouse transaction.

## Warehouse location model

Physical storage and handling policy are separate dimensions.

Examples:

```text
P-1-A115E181
P-1-V112A110
P-1-R120D211
P-1-H119C160
P-1-X115N112
P-1-C124A110
P-1-F129F142
P-1-HAZ-A123E110
P-1-HAZ-X119T110
P-1-HRV132A110
TSCRET001
TSCRETCHL01
TSCRETFRZ01
DMG
SPECIAL
```

Known semantics include ambient, produce, chilled, frozen, HAZ, HRV, temporary return/unpack locations and damaged/quarantine storage. See `docs/LOCATION_GRAMMAR.md`.

## Architecture

```text
 Android PDA ───────┐
                    │ HTTPS
 Next.js Web ───────┼────► FastAPI
                    │         │
                    │         ├────► PostgreSQL / Neon
                    │         │       transactional truth
                    │         │
                    │         └────► MongoDB Atlas
                    │                 telemetry/read models
                    │
                    └──── server-authoritative execution
```

PostgreSQL remains authoritative. MongoDB telemetry is deliberately best-effort and cannot block inventory execution.

## Event distribution and observability

v0.5 adds a PostgreSQL-backed transactional outbox. Business events are inserted in the same database transaction as the authoritative change, then a background dispatcher publishes them independently.

Current outbox topics include sensitive admin audit changes, worker-state transitions, atomic order claims, replenishment completion and operational incidents. The dispatcher uses PostgreSQL `SKIP LOCKED`, retry/backoff, MongoDB telemetry when configured, and an optional incident webhook.

OpenTelemetry instrumentation covers FastAPI and SQLAlchemy, with request counters, server-error counters, latency histograms, structured JSON request logs and `X-Request-ID`. Configure `OTEL_EXPORTER_OTLP_ENDPOINT` to export traces/metrics to an OTLP collector.

## Database migrations

v0.4 introduces Alembic.

The migration runner supports both cases:

- **existing production database:** detect the pre-Alembic schema, stamp the verified baseline, then apply later revisions;
- **fresh database:** create current metadata once, stamp the current migration head, then future changes are Alembic-driven.

PostgreSQL migration startup is protected by an advisory lock so concurrent serverless cold starts cannot race schema changes.

Migration files live under:

```text
backend/alembic/
backend/alembic/versions/
```

The older `backend/migrations/0001_initial.sql` and `0002_ops_platform.sql` remain historical/bootstrap references rather than the forward schema-evolution mechanism.

## Local development

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8080
```

Run tests:

```bash
cd backend
pytest -q
```

### Web

```bash
cd web
npm install
NEXT_PUBLIC_API_BASE_URL=http://localhost:8080 npm run dev
```

### Android

For a debug build:

```bash
cd android
gradle --no-daemon :app:assembleDebug
```

For a release build:

```bash
FULFILLOS_API_BASE_URL=https://your-host.example/api \
gradle --no-daemon :app:assembleRelease
```

## Authentication and secrets

Production bootstrap credentials remain GitHub/Vercel secrets:

```text
VERCEL_TOKEN
MONGODB_URI
BOOTSTRAP_PICKER_PASSWORD
BOOTSTRAP_SUPERVISOR_PASSWORD
```

Bootstrap credentials are intended for initial/recovery access, not as the long-term user-management model. Existing secret plaintext should be rotated rather than “recovered”.

## CI/CD

GitHub Actions currently validates:

- backend test suite;
- Next.js build;
- Android debug + release assembly;
- production deployment;
- production health payload;
- PostgreSQL connectivity;
- telemetry connectivity;
- production web root;
- production-connected Android artifacts.

The production APK artifact name is generated from Gradle version metadata, e.g. `FulfillOS-v0.5.1-production-apks`.

## What remains

v0.5 closes the previously listed handheld-screen, scanner/camera, browser-session, audit, outbox and observability foundations. The main remaining production work is:

1. replace internal debug-key release signing with protected production signing / Play App Signing;
2. integrate verified email/SMS self-service password recovery instead of manager-only temporary PIN recovery;
3. calibrate physical warehouse topology using measured walking distances, one-way paths and real congestion data;
4. validate/configure industrial scanner profiles on the exact PDA fleet used at each site and run physical workflow acceptance tests;
5. add richer live event consumption (SSE/WebSocket projections) on top of the transactional outbox so the web can eventually reduce polling;
6. run backup/restore and disaster-recovery drills for Neon plus release rollback drills;
7. add stronger privacy/retention/export controls for address, phone, salary and attendance data;
8. add statutory payroll/tax behavior only if required by the deployment jurisdiction;
9. mature multi-site/tenant isolation, site-scoped policy management and capacity calibration;
10. replace internal release signing and formalize protected changelogs/rollback artifacts before public distribution.

## Documentation

- `docs/API.md` — current API groups and important v0.5 endpoints.
- `docs/ARCHITECTURE.md` — authoritative architecture and bounded domains.
- `docs/DEPLOYMENT.md` — production deployment, Alembic and Android artifacts.
- `docs/LOCATION_GRAMMAR.md` — location identifiers and logical locations.
- `docs/RELIABILITY.md` — failure handling and concurrency invariants.
- `docs/WORKFLOWS.md` — outbound, inbound, replenishment, workforce and promotion flows.
- `docs/ROADMAP.md` — what is complete and what remains.
- `BUILD_REPORT.md` — implementation snapshot for v0.5.

## Design principle

FulfillOS should make the **correct physical/operational state easy to understand and difficult to corrupt**.

That means no hidden inventory mutations, no duplicate side effects, no stale ownership races, no fake “offline stock”, no silent rank/pay changes, no production development endpoint, and no HR/payroll access without explicit authorization.
