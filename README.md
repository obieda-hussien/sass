# FulfillOS

FulfillOS is a clean-room micro-fulfillment / dark-store execution platform built from observed warehouse workflows and first-principles system design. It does **not** copy proprietary source code, private endpoints, credentials, internal brand assets, or vendor-specific implementations.

The project is deliberately reliability-first: the server owns the truth, client actions are replay-safe, Android survives network/process/device failure, cancelled orders have explicit recovery, and operational downtime is separated from associate performance.

## Current project status

### Production foundation

The current production stack is:

- **Android PDA:** Kotlin + Jetpack Compose.
- **API:** FastAPI + SQLAlchemy.
- **Transactional system of record:** PostgreSQL / Neon.
- **Telemetry/read models:** MongoDB Atlas.
- **Supervisor UI:** Next.js Control Tower.
- **Hosting:** Vercel Services.
- **CI/CD:** GitHub Actions.
- **Production web:** https://fulfillos-nine.vercel.app
- **Production API base:** https://fulfillos-nine.vercel.app/api

The main branch already contains the warehouse execution foundation and the Android production-endpoint hardening work. Android release builds are not allowed to silently fall back to the emulator-only `10.0.2.2` endpoint.

### Workforce / employee management work

Active development currently lives on:

`feature/workforce-admin`

This branch adds the backend foundation for employee administration, attendance, overtime, payroll previews, operational-performance events, and password recovery. The backend is being implemented first; the full supervisor dashboard UI for these features is still pending.

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

The Next.js web app currently exposes the live operational overview:

- associates on site;
- waiting / offered / picking / packing / break / offline states;
- task pipeline;
- recovery-required count;
- explicit recovery queue;
- five-second refresh;
- production API-backed state.

Run locally:

```bash
cd web
npm install
NEXT_PUBLIC_API_BASE_URL=http://localhost:8080 npm run dev
```

On Vercel Services, the web UI is mounted at `/` and FastAPI is exposed under `/api`.

---

# Workforce management

The `feature/workforce-admin` branch introduces the backend foundation for managing real employees instead of keeping only bare picker usernames.

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

## Workforce API currently added on the feature branch

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

The full dashboard screens consuming these APIs are not implemented yet.

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

## Tests

```bash
cd backend
pytest -q
```

Coverage currently includes or is being expanded for:

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

### Workforce branch

- employee profile model;
- employee create/update backend;
- supervisor/admin RBAC gate;
- attendance entries;
- late-minute calculation;
- overtime tracking;
- operational performance events;
- explicit pay adjustments;
- payroll preview;
- forgot-password request model;
- temporary password issuance;
- change-password/session revocation;
- workforce unit-test foundation.

---

## What remains

The most important unfinished work is:

1. **Finish and validate `feature/workforce-admin`.**
   Run the full backend test suite, fix any integration failures, create a PR and merge only after CI is green.

2. **Build the Workforce dashboard UI.**
   Add authenticated supervisor/admin navigation, Employees list, Add Employee, Employee detail, Attendance, Performance, Payroll Preview and Password Reset Queue.

3. **Add dashboard authentication/authorization.**
   The workforce pages must not expose HR/payroll data to an unauthenticated Control Tower visitor.

4. **Add Android “Forgot password?”.**
   The app should create a reset request and clearly explain the current manager-assisted flow.

5. **Add real email/SMS recovery.**
   Introduce short-lived single-use reset tokens, rate limits and provider integration.

6. **Build shift scheduling.**
   Shift templates, rota assignment, clock-in/out, break tracking, overtime approval and attendance reconciliation.

7. **Automate operational metrics carefully.**
   Generate events such as late SLAM from authoritative task timestamps while preserving system/network/device-attribution context.

8. **Define payroll policy as configuration.**
   Overtime multipliers, bonuses and deductions should be explicit, versioned and auditable. Raw SLA metrics must not silently change pay.

9. **Add migrations.**
   Move production schema evolution from additive `create_all` bootstrap behavior to Alembic migrations before workforce schema deployment.

10. **Add full audit history.**
    Record who changed salary, role, employee profile, attendance, adjustment and password-reset state.

11. **Harden RBAC.**
    Move beyond broad roles to permission scopes such as `employees.read`, `employees.write`, `payroll.read`, `payroll.adjust`, `password_reset.resolve`.

12. **Production signing.**
    Replace internal debug-key release signing with a protected private release keystore before public distribution.

13. **Operational UX expansion.**
    Finish Android screens for Receive, Unpack, BOH Move, Damage, Cycle Count, recovery and richer exception states.

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
