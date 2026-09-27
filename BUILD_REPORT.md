# FulfillOS build report — v0.4

_Status snapshot: 28 September 2026._

## Release summary

FulfillOS v0.4 builds on the v0.3 operations platform and adds the first production-oriented governance layer around schema evolution, workforce hierarchy, rota, permissions, audit and executable replenishment.

Current Android release metadata:

- versionName: `0.4.0`
- versionCode: `5`
- minSdk: `26`
- targetSdk: `36`
- compileSdk: `37`

Current production stack:

- FastAPI + SQLAlchemy;
- PostgreSQL / Neon as transactional source of truth;
- MongoDB Atlas as non-authoritative telemetry/read-model storage;
- Next.js web surfaces;
- Kotlin + Jetpack Compose PDA client;
- Vercel Services;
- GitHub Actions CI/CD.

## Implemented in warehouse execution

### Dispatch and ownership

- hard one-picker / one-active-order database lease;
- broadcast offers to eligible AVAILABLE pickers;
- atomic first-winner claim;
- safe loser response without ownership mutation;
- supervisor/team-leader direct assignment;
- assignment timeout/release behavior;
- user-wide active-task recovery;
- operational-state gating during:
  - break;
  - picking;
  - receiving;
  - stow;
  - unpack;
  - cycle count;
  - replenishment;
  - training;
  - end-shift and other configured work;
- HAZ/HRV qualification checks;
- optional domain restrictions per worker;
- device battery/connectivity/last-location telemetry in dispatch context.

### Picking and bags

- deterministic allocation;
- FEFO-aware inventory selection when expiry lots exist;
- warm/ambient → chilled → frozen route order;
- topology-aware route optimization hooks;
- PICK / SHORT / SKIP / DAMAGED durable events;
- repeated-short evidence;
- inventory alerts;
- replenishment candidate generation;
- one or more bag/SPOO closes per order;
- full SPOO stored server-side;
- regular picker UI shows masked/last-four SPOO;
- order completion summary with item quantities and bag list;
- Order Explorer by order/external ID, picker, SPOO and date/time.

### Fulfillment availability

- holds at SITE / DOMAIN / ZONE / AISLE / BIN / SKU;
- scheduled starts/expiry;
- soft hold for new orderability/allocation;
- emergency hard-stop for active picking;
- physical stock remains unchanged;
- separate physical / fulfillable / blocked stock;
- impact preview;
- alternative enabled stock can keep a SKU orderable.

### Receive and stow

- shipment creation;
- dock check-in;
- receiving session;
- good/damaged/missing reconciliation;
- ambient/chilled/frozen/HAZ/HRV/produce domains;
- lot/expiry capture;
- HAZ/HRV qualification enforcement;
- cold-chain target-stow timer;
- stow-task generation;
- compatible-bin recommendation;
- bin-capacity filtering;
- completion returns worker to AVAILABLE.

### Replenishment v0.4

Replenishment is executable rather than recommendation-only:

- READY / ASSIGNED / CLAIMED lifecycle;
- explicit worker ownership;
- source-bin scan;
- product scan;
- destination-bin scan;
- actual-quantity confirmation;
- idempotent inventory movement;
- COMPLETED / PARTIAL terminal states;
- partial remainder task;
- manager cancellation;
- priority;
- proactive low-pick-face generation from reserve stock;
- worker state `REPLENISHING` blocks new order dispatch.

## Workforce and governance

### Employee data

- employee code;
- username;
- active state;
- full name;
- email;
- phone;
- address;
- job title;
- department;
- hire date;
- employment status;
- currency;
- base salary;
- overtime rate;
- scheduled start;
- grace period;
- notes.

### Rank ladder

Operational warehouse promotion ladder:

```text
PICKER
→ SENIOR_PICKER
→ QUALITY
→ QUALITY_LEADER
→ TEAM_LEADER
→ SUPERVISOR
```

Additional operational specializations:

- RECEIVER
- INVENTORY

Technical/governance role:

- ADMIN

Promotion behavior:

- promotion must move upward on the warehouse ladder;
- ADMIN cannot be reached through warehouse promotion;
- generic employee PATCH cannot bypass rank-change history;
- promotion reason is mandatory;
- approver is recorded;
- effective timestamp is recorded;
- old/new salary is recorded;
- salary may stay unchanged or explicitly increase;
- promotion cannot silently reduce base salary.

### Permission scopes

Implemented role/user permission grants include examples such as:

- operations.read/manage;
- employees.read/write;
- quality.read/inspect/manage;
- attendance.approve;
- shifts.manage;
- replenishment.execute/manage;
- payroll.read/adjust;
- promotions.manage;
- password_reset.resolve;
- permissions.manage;
- audit.read.

### Shift planning

- timezone-aware shift templates;
- dated shift assignments;
- roster queries;
- automatic scheduled-shift clock-in;
- automatic clock-out;
- grace-aware late minutes;
- early-leave minutes;
- worked minutes;
- overtime minutes;
- break sessions;
- leave request/review;
- overtime request/review.

### Payroll

- base salary;
- overtime preview;
- approved manual pay adjustments;
- configurable attendance deduction policy;
- late and early-leave calculation;
- performance metrics kept separate from automatic pay/rank decisions.

### Audit

v0.4 adds admin audit events for sensitive governance actions and promotion history as a first-class record.

## Operations intelligence

Implemented:

- performance rows;
- late-SLAM count/rate;
- average pick time;
- warehouse heatmap;
- expiry-risk reporting;
- demand/velocity slotting suggestions;
- route simulation;
- topology nodes/edges;
- location operational profiles;
- capacity snapshots;
- operational incidents;
- guard rules;
- cycle-count escalation from inventory alerts.

Suggestions remain advisory unless an explicit command changes operational state.

## Web

### `/` — Control Tower

Operational overview and pipeline visibility.

### `/operations`

- picker availability;
- active task;
- state/qualification context;
- manual dispatch;
- fulfillment holds;
- Order Explorer;
- performance;
- slotting;
- inbound shipment/stow state.

### `/people`

- employee onboarding;
- employee profile/pay data;
- attendance/overtime;
- payroll preview;
- pay adjustment;
- password-reset queue;
- rank promotion;
- promotion history.

## Android

Implemented/reliability foundation:

- device-bound session recovery;
- durable pending-event journal;
- reconnect/retry behavior;
- pick flow;
- broadcast offers;
- atomic accept;
- skip/short/damaged;
- multi-bag SPOO close;
- completion summary;
- worker state API integration;
- inventory tools;
- WorkManager-based background retry.

Current gap:

Receive, Unpack, BOH Move, Damage, Cycle Count, Recovery and Replenishment still need fully polished production-grade handheld Compose screens and scanner flows.

## Database migrations

v0.4 introduces Alembic:

- pre-Alembic production baseline revision;
- v0.4 governance/workforce revision;
- startup migration runner;
- fresh-database bootstrap;
- existing-database stamp + upgrade;
- PostgreSQL advisory lock around startup migration.

The historical SQL migrations remain in the repository for reference/bootstrap history but future schema evolution should go through Alembic.

## CI/CD and production

Implemented:

- backend tests;
- Next.js build;
- Android debug/release build;
- production Vercel deployment;
- public production health verification;
- PostgreSQL connectivity assertion;
- telemetry connectivity assertion;
- web-root verification;
- production-connected Android APK generation;
- Android artifact names derived from Gradle version metadata.

Latest merged `main` checks for v0.4 are green.

## Remaining high-priority work

1. complete full Android operational screens;
2. industrial scanner integration + camera fallback;
3. production signing / Play App Signing;
4. short-lived browser sessions using HttpOnly/SameSite cookies + CSRF protection;
5. expand audit coverage for every sensitive profile/payroll edit;
6. verified email/SMS password recovery;
7. transactional outbox + event distribution;
8. observability and incident notification;
9. measured warehouse topology calibration;
10. richer replenishment SLA/priority and handheld UX;
11. protected release/changelog/rollback process;
12. data privacy/retention/export controls;
13. statutory payroll/tax logic only if required.

## Validation principle

A feature is considered production-complete only when its server-side invariant, persistence model, permission boundary, retry behavior, tests and operational recovery behavior are all defined—not merely when a UI control exists.
