# FulfillOS

FulfillOS is a clean-room micro-fulfillment / dark-store execution platform built from observed warehouse workflows and first-principles system design. It does **not** copy proprietary source code, private endpoints, credentials, internal brand assets, or vendor-specific implementations.

The project is deliberately reliability-first: the server owns the truth, client actions are replay-safe, Android survives network/process/device failure, cancelled orders have explicit recovery, and operational downtime is separated from associate performance.

## Current project status

_Status snapshot: 27 September 2026._

### Production foundation

The current production stack is:

- **Android PDA:** Kotlin + Jetpack Compose.
- **Current Android app version:** `0.2.2` (`versionCode 4`).
- **API:** FastAPI + SQLAlchemy.
- **Transactional system of record:** PostgreSQL / Neon.
- **Telemetry/read models:** MongoDB Atlas.
- **Supervisor UI:** Next.js Control Tower.
- **Workforce UI:** authenticated Next.js People & Payroll workspace.
- **Hosting:** Vercel Services.
- **CI/CD:** GitHub Actions.
- **Production web:** https://fulfillos-nine.vercel.app
- **Production API base:** https://fulfillos-nine.vercel.app/api

The main branch contains the warehouse execution foundation, production Vercel/Neon/Atlas deployment, Android production-endpoint hardening, workforce administration, password recovery, and the People & Payroll dashboard.

Release Android builds are not allowed to silently fall back to the emulator-only `10.0.2.2` endpoint: production release builds require an explicit HTTPS API URL and fail at build time otherwise.

### Current delivery state

| Area | Status |
| --- | --- |
| Warehouse inventory ledger | Implemented |
| Picking / short-pick / recovery | Implemented |
| Receive / Unpack / BOH / Damage / Cycle Count backend | Implemented |
| Android resilient session + durable pick journal | Implemented |
| Next.js Control Tower | Production |
| Vercel Services | Production |
| Neon PostgreSQL | Production authoritative DB |
| MongoDB Atlas telemetry | Connected |
| Workforce backend | Merged to `main` |
| People & Payroll dashboard | Merged to `main` |
| Android Forgot Password request | Merged to `main` |
| Release signing | Internal debug-key signing only; production keystore still pending |
| Full statutory payroll/tax engine | Not implemented |
| Alembic schema migrations | Pending |

The comprehensive documentation update is tracked separately so the README can describe both what is already on `main` and the next engineering phases accurately.

---

## Problems FulfillOS is designed to prevent

The architecture specifically targets failure modes such as:

- a scan appears locally but never commits on the server;
- connectivity drops and the picker UI hangs indefinitely;
- a PDA restarts/logs out and the active task disappears;
- an order is cancelled after one or more units were already picked;
- duplicate retries move inventory twice;
- stale state sends the associate backwards through the pick;
- attempted scans are confused with server-confirmed picks;
- technical/network downtime is counted as associate delay;
- a production Android build accidentally points at an emulator URL;
- operational exceptions disappear instead of being explicitly resolved.

FulfillOS treats these as system-design problems rather than isolated UI bugs.

---

## Repository layout

```text
backend/      FastAPI API, transactional inventory ledger, workforce services and tests
web/          Next.js supervisor Control Tower
dashboard/    Lightweight fallback/static dashboard
android/      Kotlin + Jetpack Compose PDA client
docs/         Architecture, reliability, location grammar, deployment and roadmap
infra/        Local PostgreSQL / Redis / NATS infrastructure
scripts/      Demo and development flows
```

---

## Architecture

```text
                         ┌──────────────────────┐
                         │  Supervisor / Admin  │
                         │ Next.js ControlTower │
                         └──────────┬───────────┘
                                    │ HTTPS
                                    ▼
┌──────────────┐          ┌──────────────────────┐
│ Android PDA  │ ───────▶ │      FastAPI API     │
│ Compose      │ ◀─────── │ auth/tasks/inventory │
└──────┬───────┘          └───────┬──────────────┘
       │                           │
       │ durable local queue       ├─────────────▶ PostgreSQL / Neon
       │ + session recovery        │               authoritative state
       │                           │
       └───────────────────────────┴─────────────▶ MongoDB Atlas
                                                   telemetry/read models
```

PostgreSQL remains authoritative for inventory, orders, sessions, tasks and payroll/workforce records. MongoDB Atlas is intentionally best-effort telemetry/read-model storage and must never become the authoritative inventory ledger by accident.

---

## Core reliability invariants

1. **The server-authoritative ledger is the source of truth.**
2. **Every inventory-changing client action has a globally unique event ID.**
3. **The PDA persists an event before the first network transmission.**
4. **Retries are idempotent.**
5. **UI progress is server-confirmed progress, not merely attempted scans.**
6. **Task snapshots are versioned and client sequence conflicts are rejected.**
7. **A partially picked cancelled order becomes an explicit recovery flow.**
8. **Network/system/device downtime is attributed separately from associate active time.**
9. **Authentication is device-bound and refreshable after process/device recovery.**
10. **Production release APKs require an HTTPS API endpoint.**

---

## Warehouse location model

Physical storage and handling policy are modeled as separate dimensions.

Examples currently understood by the parser/configuration:

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

Typical interpretation:

```text
floor/site + classification + fixture + aisle + level + slot
```

Known concepts include:

- `A`: regular/ambient fixture.
- `V`: produce/vegetables.
- `R`: chips/snack rack.
- `H`: hanging/peg storage.
- `X`: drawer-style storage.
- `C`: chilled.
- `F`: frozen.
- `HAZ`: hazardous handling classification.
- `HRV`: high-value handling/security classification.
- `TSCRET...`: temporary unpack/returns locations by temperature class.
- `DMG`: damaged/non-sellable stock.
- `SPECIAL`: explicit exception/special handling location.

`HAZ` and `HRV` are modeled orthogonally to fixture type rather than hard-coded as mutually exclusive physical zones.

---

## Warehouse workflows implemented or scaffolded

### Inventory

- product ↔ barcode mapping;
- product → locations;
- location → products;
- on-hand vs reserved quantity;
- event-based inventory movements;
- idempotent movement events;
- cycle counting;
- damage handling;
- temporary logical locations;
- storage compatibility checks.

### Receive / Unpack / BOH

```text
Receive / Return
      ↓
Temperature-aware Unpack
      ↓
Temporary tote
      ↓
BOH Move
      ↓
Final compatible storage
```

Open unpack sessions are resumable so a PDA retry/reboot does not accidentally create duplicate workflow state.

### Picking

```text
READY
  ↓
OFFERED
  ↓
ACCEPTED
  ↓
PICKING
  ↓
PICKED
  ↓
PACK_RACK
  ↓
STAGED
  ↓
HANDOFF
  ↓
COMPLETED
```

The picker flow supports:

- server-owned active tasks;
- associate/device ownership;
- durable scan events;
- client sequence validation;
- bin/product validation;
- duplicate retry protection;
- explicit short-pick events;
- server-confirmed progress;
- order/task reconciliation.

### Cancellation recovery

Cancellation is state-dependent.

If inventory was already physically picked, FulfillOS does not simply mark the order cancelled and pretend stock returned itself. The task moves into an explicit recovery state and the inventory must be reconciled/stowed through a controlled workflow.

### SLA / downtime

Operational timing distinguishes:

- associate active time;
- network downtime;
- device downtime;
- system downtime;
- explicit operational exceptions.

Observed local pick-target behavior can be configured separately from actual payroll or disciplinary policy.

---

## Android PDA

The Android application is built with Kotlin + Jetpack Compose and includes the reliability foundation for:

- trusted PDA sign-in;
- device-bound access/refresh sessions;
- task resume after process/device recovery;
- durable event journal;
- offline/reconnect handling;
- pick scanning;
- short-pick reporting;
- inventory viewer;
- barcode lookup;
- boot-time queue replay;
- production API configuration.

### Production endpoint safety

Debug builds may intentionally use a development endpoint.

Release builds must receive `FULFILLOS_API_BASE_URL` and it must begin with `https://`. This prevents a release APK from silently shipping with `http://10.0.2.2:8080`.

---

## Supervisor Control Tower

The Next.js web app exposes two supervisor surfaces.

### Control Tower (`/`)

- associates on site;
- waiting / offered / picking / packing / break / offline states;
- task pipeline;
- recovery-required count;
- explicit recovery queue;
- five-second refresh;
- production API-backed state.

### People & Payroll (`/people`)

- supervisor/admin sign-in;
- employee list and profiles;
- create employee onboarding form;
- employee code, username, role and job metadata;
- email, phone and address;
- salary and overtime-rate configuration;
- attendance + clock-in/out entry;
- automatic late-minute calculation after grace period;
- approved overtime recording;
- operational-event recording, including `LATE_SLAM`, `LATE_DELIVERY`, `SYSTEM_DELAY` and `NETWORK_DELAY`;
- explicit payroll adjustments with reason and approval;
- payroll preview;
- password-reset request queue;
- one-time temporary-password issuance.

Run locally:

```bash
cd web
npm install
NEXT_PUBLIC_API_BASE_URL=http://localhost:8080 npm run dev
```

On Vercel Services, the web UI is mounted at `/` and FastAPI is exposed under `/api`.

---

# Workforce management

The first workforce-management slice is now merged into `main`. It manages real employee records instead of keeping only bare picker usernames, and it includes both backend APIs and a supervisor-facing `/people` UI.

## Employee profile

Each employee can have:

- internal employee code;
- username/login;
- role;
- active/inactive account state;
- full name;
- email;
- phone number;
- address;
- job title;
- department;
- hire date;
- employment status;
- payroll currency;
- base salary;
- overtime hourly rate;
- scheduled shift start;
- grace period;
- manager notes.

Operational credentials and HR information are intentionally represented as separate concerns even though they are linked by `user_id`.

## Roles

Currently recognized role classes include:

- `PICKER`
- `RECEIVER`
- `INVENTORY`
- `SUPERVISOR`
- `ADMIN`

Workforce-management endpoints require `SUPERVISOR` or `ADMIN`.

More granular permission scopes are planned before this becomes a mature HR/payroll product.

## Attendance

The new attendance model can record:

- scheduled start;
- actual clock-in;
- clock-out;
- late minutes;
- overtime minutes;
- approval state;
- source;
- notes;
- approving manager.

Late minutes are calculated after the configured grace period.

Future work will connect this to shift scheduling and real clock-in/check-in events rather than relying only on manager-created entries.

## Operational performance

A separate `PerformanceEvent` model can record reviewable events such as:

- `LATE_SLAM`;
- late completion;
- operational exception;
- manual recognition/positive event;
- other future metrics.

These events are **not automatically converted into salary deductions**.

That separation is intentional: an SLA event can be caused by stock problems, device failure, network downtime, order mutation or system failure. Payroll-impacting actions therefore require an explicit approved pay adjustment instead of silently penalizing an employee from a raw warehouse metric.

## Payroll preview

Current payroll preview combines:

```text
base salary
+ approved overtime
+ explicit approved pay adjustments
= estimated total
```

The preview also reports operational context separately:

- total late minutes;
- overtime minutes;
- completed orders;
- performance-event counts such as late SLAM.

This is currently a **payroll preview**, not a full statutory Egyptian payroll/tax engine.

## Password recovery

The branch adds:

- public `forgot-password` request without account enumeration;
- pending reset requests visible to supervisors/admins;
- manager-issued temporary password;
- password-change endpoint;
- session revocation after password change.

Current recovery is intentionally manager-assisted because no email/SMS provider has been connected yet.

Planned production flow:

```text
Forgot password
      ↓
email / SMS identity verification
      ↓
short-lived single-use reset token
      ↓
new password
      ↓
revoke old sessions
      ↓
re-authenticate trusted PDA
```

Temporary/generated passwords are shown only at creation/reset time and are not stored in plaintext.

---

## Workforce API

```text
POST  /auth/forgot-password
POST  /auth/change-password

GET   /admin/employees
POST  /admin/employees
GET   /admin/employees/{user_id}
PATCH /admin/employees/{user_id}

POST  /admin/employees/{user_id}/attendance
POST  /admin/employees/{user_id}/performance-events
POST  /admin/employees/{user_id}/pay-adjustments
GET   /admin/employees/{user_id}/payroll-preview

GET   /admin/password-resets
POST  /admin/password-resets/{reset_id}/issue-temporary-password
```

These APIs are consumed by the authenticated `/people` workspace. The current UI covers onboarding, employee overview, attendance/overtime entry, operational events, explicit pay adjustments and the password-reset queue.

---

## Authentication and secrets

Production bootstrap credentials are configured through GitHub/Vercel secrets rather than committed to the repository.

Relevant names include:

```text
VERCEL_TOKEN
MONGODB_URI
BOOTSTRAP_PICKER_PASSWORD
BOOTSTRAP_SUPERVISOR_PASSWORD
```

GitHub Actions secrets are write-only from normal repository workflows/interfaces; their plaintext value should not be expected to be recoverable later.

If the current bootstrap password is unknown, rotate the corresponding secret to a known strong value and redeploy rather than trying to recover the old plaintext password.

---

## Local backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8080
```

For the demo seed only:

```text
username: picker1
password: demo1234
device:   PDA-DEMO-001
```

Production demo seeding is disabled.

---

## Tests and CI

```bash
cd backend
pytest -q
```

The current `main` branch has green GitHub Actions for backend tests, the Next.js build and Android APK assembly, and the production deployment workflow has completed successfully against Vercel/Neon/Atlas.

Coverage includes or is being expanded for:

- location parsing;
- idempotent inventory movement;
- reservation correctness;
- duplicate pick scans;
- sequence conflicts;
- cancellation recovery;
- downtime-aware SLA;
- retry-safe fulfillment transitions;
- unpack-session recovery;
- production bootstrap users;
- employee creation;
- attendance/late-minute calculation;
- overtime/payroll preview;
- performance events;
- password recovery.

---

## Production deployment

See `docs/DEPLOYMENT.md`.

The deployment pipeline handles:

1. Vercel Services project configuration.
2. Neon PostgreSQL.
3. MongoDB Atlas telemetry configuration.
4. production environment variables/secrets;
5. Next.js + FastAPI deployment;
6. production health validation;
7. Android debug/release builds pointed at the production API;
8. downloadable GitHub Actions artifacts.

The release APK is currently an internal installable release signed with the debug signing configuration. A private production/Play release key is still required before store distribution.

---

## What is done now

### Warehouse core

- transactional inventory ledger;
- product/barcode/location model;
- allocation and reservations;
- picking task lifecycle;
- durable/idempotent pick events;
- shortage flow;
- stage/handoff/completion;
- cancellation recovery;
- cycle count;
- damage;
- receive/unpack/BOH move;
- device/session recovery;
- downtime-aware SLA;
- supervisor Control Tower;
- Vercel production deployment;
- Neon authoritative database;
- MongoDB Atlas telemetry;
- Android debug/release CI artifacts;
- production endpoint hardening.

### Workforce / People & Payroll

- employee profile model;
- employee create/update backend;
- supervisor/admin RBAC gate;
- employee code, contact details, address, role, job title and department;
- salary and overtime-rate configuration;
- attendance entries;
- late-minute calculation with grace period;
- overtime tracking;
- operational performance events;
- explicit approved pay adjustments;
- payroll preview;
- forgot-password request model;
- Android `Forgot password?` action;
- password-reset queue in the dashboard;
- one-time temporary-password issuance;
- change-password/session revocation;
- authenticated `/people` supervisor UI;
- workforce unit-test coverage.

---

## What remains

The next important engineering phases are:

1. **Replace bootstrap-secret dependence with normal account administration.**
   Keep bootstrap users only for initial recovery/setup, then create and manage normal supervisors/admins from the workforce system. Secrets are write-only and should be rotated rather than treated as retrievable passwords.

2. **Add Alembic migrations before further production schema growth.**
   Workforce tables currently rely on additive startup creation. Versioned forward/backward migrations are needed before the data model changes further.

3. **Harden workforce web authentication.**
   The current People & Payroll UI is an authenticated MVP. Move browser sessions away from long-lived tokens in `localStorage` toward short-lived server/session cookies with CSRF protection and explicit logout/session revocation.

4. **Move from broad roles to permission scopes.**
   Add permissions such as `employees.read`, `employees.write`, `payroll.read`, `payroll.adjust`, `attendance.approve` and `password_reset.resolve`.

5. **Add complete HR/payroll audit history.**
   Every salary change, pay adjustment, role change, attendance edit, profile edit and password-reset action should record actor, old value, new value, timestamp and reason.

6. **Build real shift scheduling.**
   Add shift templates, weekly rota assignment, expected clock-in/out, breaks, leave/absence, overtime requests and supervisor approval.

7. **Automate operational performance events from authoritative timestamps.**
   Generate late SLAM / late delivery / exception events automatically while preserving network, system and device downtime so technical failures are not misattributed to the worker.

8. **Keep payroll policy explicit and reviewable.**
   Raw lateness/SLA events must never silently deduct salary. Bonuses, deductions, overtime multipliers and attendance policies should be configured, versioned and approved explicitly.

9. **Add real self-service password recovery.**
   Integrate verified email/SMS, rate limiting, single-use expiring reset tokens and security notifications. The current manager-assisted temporary-password flow remains the fallback.

10. **Finish the remaining Android operational tools.**
    The reliability foundation exists, but Receive, Unpack, BOH Move, Damage, Cycle Count, recovery and richer exception UX still need full production-grade handheld screens.

11. **Add production signing and release management.**
    Replace the internal debug-key release signature with a protected release keystore / Play App Signing flow, versioned releases, changelogs and rollback artifacts.

12. **Clean up Android artifact naming.**
    The app on `main` is currently version `0.2.2`, while one production workflow artifact can still carry an older `v0.2.1` display name. Artifact names should be derived automatically from Gradle version metadata to prevent label drift.

13. **Add notification and incident workflows.**
    Supervisor alerts for recovery-required orders, repeated device/network failures, excessive short picks, cold-chain exceptions, pending password resets and attendance exceptions should be configurable and auditable.

14. **Expand workforce analytics without turning metrics into automatic punishment.**
    Useful additions include units/hour, pick accuracy, short-pick rate, recovery rate, average acceptance time, late-SLAM counts, device-downtime minutes and positive-recognition events, all presented with operational context.

15. **Improve data privacy and retention controls.**
    HR fields such as address, phone, salary and attendance need stricter access controls, retention policies, export/delete processes and separation from general warehouse telemetry.

---

## Design principle

FulfillOS should make the **correct warehouse state easy to understand and difficult to corrupt**.

That means:

- no hidden inventory mutations;
- no silent task disappearance;
- no duplicate side effects from retries;
- no optimistic progress presented as committed truth;
- no automatic worker penalty from ambiguous technical failures;
- no plaintext secrets in source control;
- no HR/payroll access without explicit authorization;
- no production release APK pointing at a development endpoint.

---

## Operations platform v0.3

The v0.3 operations slice extends the reliability/workforce foundation with:

- hard one-picker / one-active-order ownership enforced by a database-backed lease;
- broadcast offers with atomic first-winner claims plus supervisor direct assignment;
- worker operational-state gating during break, receiving, stow, unpack, cycle count, training and similar work;
- picker domain restrictions, HAZ/HRV qualifications and proximity-aware dispatch context;
- Order Explorer search by order/external ID, picker username, full SPOO or suffix, and date/time range;
- multi-bag SPOO close and final picker completion summary;
- warm → chilled → frozen routing, FEFO-aware allocation, topology-aware route optimization and congestion hooks;
- fulfillment holds at site/domain/zone/aisle/bin/SKU scope while preserving physical stock truth;
- separate physical, fulfillable and blocked stock;
- skip, short and damaged-item workflows, repeated-short alerts, replenishment candidates and cycle-count escalation;
- Receive v3 core: shipment, dock check-in, receiving, discrepancy reconciliation, cold-chain timer, stow recommendations and capacity checks;
- shift clock-in/out calculations for late, early-leave, worked time and overtime;
- explicit payroll attendance-deduction policy; performance metrics do not automatically change role or pay;
- warehouse heatmap, expiry-risk reporting, route simulation, task handover, operational incidents and configurable fulfillment guards;
- a Next.js `/operations` console and Android PDA support for broadcast offers, durable pick exceptions and multi-bag completion.

The PostgreSQL schema extension lives in `backend/migrations/0002_ops_platform.sql`. Detailed workflow and implementation notes are in `BUILD_REPORT.md`, `docs/WORKFLOWS.md`, and `docs/ROADMAP.md`.
