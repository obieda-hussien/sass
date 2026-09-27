# FulfillOS

FulfillOS is a clean-room micro-fulfillment / dark-store execution platform built from observed warehouse workflows and first-principles system design. It does **not** copy proprietary source code, private endpoints, credentials, internal brand assets, or vendor-specific implementations.

The project is reliability-first: PostgreSQL owns transactional truth, client actions are replay-safe, Android can recover from network/process/device failure, inventory mutations are idempotent, picker/order ownership is enforced server-side, and workforce/payroll decisions remain explicit and auditable.

## Current status

_Status snapshot: 28 September 2026._

| Component | Current state |
| --- | --- |
| FulfillOS release | **v0.4.0** |
| Android | Kotlin + Jetpack Compose, versionCode **5**, minSdk 26, targetSdk 36 |
| API | FastAPI + SQLAlchemy |
| Primary database | PostgreSQL / Neon |
| Schema management | **Alembic** with safe pre-Alembic baseline + startup migration runner |
| Telemetry/read models | MongoDB Atlas, non-authoritative |
| Web | Next.js Control Tower + Operations + People & Payroll |
| Hosting | Vercel Services |
| CI/CD | GitHub Actions |
| Production | https://fulfillos-nine.vercel.app |
| Production API | https://fulfillos-nine.vercel.app/api |
| Latest merged release | PR #26, FulfillOS v0.4 |

The latest `main` build/deploy checks are green. Production deployment validates `/api/health`, PostgreSQL connectivity, telemetry connectivity, the web root, and then builds production-connected Android APK artifacts.

## What v0.4 contains

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

### Replenishment v0.4

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
- one-time temporary-password issuance;
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

v0.4 adds permission scopes and user/role overrides.

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

- employee onboarding;
- profile/contact/job/payroll data;
- attendance/overtime;
- payroll preview;
- pay adjustments;
- password resets;
- rank promotion workflow;
- promotion history.

## Android PDA

The Android app currently targets the server-authoritative execution model and includes:

- trusted device login + refresh;
- durable pending-event journal;
- offline/reconnect handling;
- active-task recovery;
- broadcast offer discovery;
- atomic accept;
- pick scanning;
- skip / short / damaged flows;
- multi-bag SPOO close;
- order-completion summary;
- worker operational-state integration;
- inventory/barcode tools;
- WorkManager-backed retry infrastructure.

The project includes models/routing for Receive, Cycle Count, Recovery and Replenishment operational screens, but several of those handheld experiences still need full production-grade Compose workflows and scanner UX.

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

The production APK artifact name is generated from Gradle version metadata, e.g. `FulfillOS-v0.4.0-production-apks`.

## What remains

The largest remaining engineering work is:

1. finish full production Compose screens for Receive, Unpack, BOH Move, Damage, Cycle Count, Recovery and Replenishment;
2. add industrial scanner profile adapters and camera fallback scanner;
3. replace internal debug-key release signing with protected production signing / Play App Signing;
4. move browser authentication from long-lived localStorage tokens to short-lived HttpOnly/SameSite sessions with CSRF protection;
5. expand audit coverage to every sensitive employee/profile/payroll edit;
6. integrate verified email/SMS self-service password recovery;
7. add transactional outbox + event distribution for scalable live projections;
8. add OpenTelemetry traces, structured production metrics and stronger incident alerting;
9. calibrate physical warehouse topology with measured walk distances, one-way paths and congestion data;
10. complete richer replenishment priority/SLA UX and worker handheld screens;
11. add statutory payroll/tax behavior only if/when required by the deployment jurisdiction;
12. implement protected release management, changelogs and rollback artifacts;
13. add stronger privacy/retention controls for address, phone, salary and attendance data.

## Documentation

- `docs/API.md` — current API groups and important v0.4 endpoints.
- `docs/ARCHITECTURE.md` — authoritative architecture and bounded domains.
- `docs/DEPLOYMENT.md` — production deployment, Alembic and Android artifacts.
- `docs/LOCATION_GRAMMAR.md` — location identifiers and logical locations.
- `docs/RELIABILITY.md` — failure handling and concurrency invariants.
- `docs/WORKFLOWS.md` — outbound, inbound, replenishment, workforce and promotion flows.
- `docs/ROADMAP.md` — what is complete and what remains.
- `BUILD_REPORT.md` — implementation snapshot for v0.4.

## Design principle

FulfillOS should make the **correct physical/operational state easy to understand and difficult to corrupt**.

That means no hidden inventory mutations, no duplicate side effects, no stale ownership races, no fake “offline stock”, no silent rank/pay changes, no production development endpoint, and no HR/payroll access without explicit authorization.
