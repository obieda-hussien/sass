# FulfillOS reliability design — v0.5

## Reliability goals

FulfillOS is designed so that network loss, duplicate retries, stale clients, worker-state changes and concurrent claims do not corrupt warehouse truth.

The central rule is:

> UI intent is not truth; committed server state is truth.

## Failure: scan spinner after Wi-Fi drop

Bad behavior:

```text
request
→ network disappears
→ UI spins forever
→ worker changes screen / restarts app
→ state becomes ambiguous
```

FulfillOS behavior:

```text
persist local event
→ attempt transmit
→ timeout/offline
→ keep event pending
→ reconnect observer
→ refresh auth if required
→ replay same event id
→ server idempotently ACKs
→ client replaces projection with authoritative snapshot
```

The client distinguishes:

- Offline
- Reconnecting
- Pending sync
- Server confirmed

## Failure: duplicate retry changes stock twice

Every inventory-changing event has a unique `event_id`.

The server treats a repeated event ID as read-after-write rather than a second mutation.

This applies to picking, replenishment and retryable v0.5 operational commands.

## Failure: client counter disagrees with server

FulfillOS distinguishes:

```text
attempted locally
pending server acknowledgement
server-confirmed
```

Completion counters use only server-confirmed state.

## Failure: stale response sends the worker backwards

Protection:

- `server_version` on task snapshots;
- monotonic `client_seq`;
- out-of-order new commands rejected;
- duplicate known event IDs accepted idempotently;
- conflict responses return authoritative state;
- client replaces stale local projection instead of heuristically merging it.

## Failure: two pickers accept the same broadcast order

The UI is not responsible for preventing this race.

The backend uses an active pick lease and atomic claim path.

```text
broadcast offer
  ├─ picker A accepts
  ├─ picker B accepts
  └─ picker C accepts
          ↓
      atomic claim
          ↓
      first commit wins
          ↓
      one task owner
      losers receive conflict
```

The loser cannot steal or mutate the task after the first claim.

## Failure: one picker gets two active orders

A picker-level active lease prevents a second active pick task from being acquired.

This invariant is enforced server-side even if:

- two PDA requests race;
- the same account is used on multiple devices;
- a supervisor tries manual assignment;
- a stale UI still shows an old offer.

## Failure: picker is on break/receiving/replenishment but receives an order

Dispatch checks operational runtime state.

Examples of non-dispatchable states include:

- BREAK
- PICKING
- receiving variants
- STOWING
- UNPACKING
- CYCLE_COUNT
- REPLENISHING
- training/end-shift states

Manual assignment uses the same eligibility model rather than bypassing it.

## Failure: HAZ/HRV work reaches an unqualified worker

Task/shipment requirements are compared with active worker qualifications.

Optional worker domain profiles can further constrain dispatch.

A missing qualification rejects the operation rather than relying on a warning in the UI.

## Failure: a zone is “offline” so inventory is zeroed

FulfillOS never models operational availability by falsifying stock.

Instead:

```text
physical stock
- stock hidden by active fulfillment holds
= fulfillable stock
```

A hold can target:

- site;
- domain;
- zone;
- aisle;
- bin;
- SKU.

The on-hand ledger remains unchanged.

## Failure: active order keeps picking from an unsafe area

Normal hold:

- blocks new orderability/allocation.

Emergency hard stop:

- additionally rejects pick execution from affected locations.

This separates commercial availability from immediate safety/operational shutdown.

## Failure: replenishment moves the wrong product/bin

v0.4 replenishment requires an explicit sequence:

```text
claim task
→ source bin scan
→ item scan
→ destination bin scan
→ quantity confirmation
→ idempotent ledger movement
```

The system validates:

- task ownership;
- source location;
- product barcode;
- destination;
- storage compatibility;
- quantity.

Partial completion can generate a remainder task.

## Failure: mid-order cancellation

Cancellation is a state transition, not task disappearance.

If nothing has been physically picked, the task may close normally.

If stock is already in the pick tote:

```text
order cancellation
→ RECOVERY_REQUIRED
→ explicit recovery/stow
→ inventory reconciliation
```

If handoff already occurred, the system uses a return/recovery workflow rather than pretending the stock is back on shelf.

## Failure: PDA reboot/logout

Server:

- owns task/order truth.

Android:

- owns a durable local journal of unacknowledged events.

After restart:

```text
restore/refresh session
→ fetch active task
→ load pending journal
→ replay in order
→ receive authoritative snapshot
→ resume work
```

## Failure: technical outage becomes employee punishment

FulfillOS tracks wall time and effective accountable time separately.

```text
wall elapsed
- approved network downtime
- backend wait
- device recovery
- system exception
= effective associate elapsed
```

Late-SLAM evidence is generated from authoritative timing and configured downtime exclusions.

Performance evidence does not automatically change salary/rank.

## Failure: promotion/pay changes happen silently

Warehouse rank changes are separated from generic employee profile edits.

Promotion requires:

- upward valid rank;
- reason;
- approver;
- effective time;
- old/new salary record.

Generic PATCH cannot silently perform warehouse promotion.

Payroll deductions are applied only when an explicit policy enables them.

## Failure: concurrent serverless starts race schema upgrades

v0.4 Alembic startup migration uses a PostgreSQL advisory lock.

```text
instance A ─┐
instance B ─┼─► advisory lock ─► migrate once ─► release
instance C ─┘
```

Existing pre-Alembic databases are stamped at a verified baseline before later revisions run.

## Failure: production APK points at emulator backend

Release build requires an explicit HTTPS API base URL.

A missing/non-HTTPS value fails the build.

Debug may intentionally use `10.0.2.2`; release may not silently inherit it.

## Failure: artifact version label drifts from app version

CI/CD derives APK filenames from Gradle `versionName`.

The release artifact label therefore follows the app metadata automatically.

## Failure: telemetry outage stops warehouse execution

MongoDB Atlas is best-effort telemetry only.

Telemetry failure cannot become a required dependency for transactional inventory commands.

PostgreSQL remains authoritative.

## Reliability roadmap

Still planned:

- transactional outbox;
- stronger distributed event publication;
- OpenTelemetry tracing;
- live SSE/WebSocket projection with replay;
- backup/restore drills;
- incident notification;
- industrial scanner diagnostics;
- more exhaustive failure injection tests.


## Failure: stale PDA is still shown as online

v0.5 does not trust a historical `device.status=ONLINE` by itself.

Android sends a heartbeat every five seconds. Dispatch requires a fresh heartbeat inside the configured presence window; otherwise the worker receives `PDA_NOT_CONNECTED` or `PDA_OFFLINE_OR_STALE` and cannot receive a new order. The control tower also classifies stale devices as offline.

## Failure: employee keeps using a temporary onboarding PIN

New employee/reset PINs are numeric and generated as six digits unless an admin explicitly supplies a 6–10 digit PIN.

A new account starts with `must_change_password=true`. Login itself succeeds so the trusted PDA can authenticate, but warehouse API dependencies return HTTP 428 until the employee completes the personal-PIN flow. Completion revokes the temporary session and issues a rotated session.

## Failure: manager reset leaves stolen/old sessions alive

Username changes, emergency PIN resets and user deactivation revoke existing session tokens. Soft deletion also disables the user, so refresh authentication rejects the account while historical orders, payroll and audit references remain intact.

## Failure: XSS reads the manager bearer token

The v0.5 web console no longer stores FastAPI bearer credentials in `localStorage`. Next.js keeps access/refresh credentials in HttpOnly SameSite cookies and performs backend calls through a BFF proxy. Unsafe browser methods require CSRF validation.

## Failure: telemetry/alert system is down during a warehouse transaction

External publication is decoupled using the transactional outbox:

```text
business transaction
  ├─ authoritative row changes
  └─ outbox row
      ↓ commit
background dispatcher
      ↓ retry/backoff
external sinks
```

The warehouse transaction does not depend on MongoDB telemetry or an incident webhook. Failed publications remain retryable and cannot silently undo committed inventory/task/workforce state.

## Failure: two app instances publish the same outbox batch

On PostgreSQL the dispatcher selects work using `FOR UPDATE SKIP LOCKED`. Multiple warm instances can process available events without selecting the same locked batch.

## Failure: production latency/errors become invisible

OpenTelemetry instruments FastAPI and SQLAlchemy. Request count, HTTP 5xx count and duration histograms are produced, and structured request logs include `X-Request-ID`. OTLP export can be enabled without changing business code.


## Failure: website says OFFLINE while the PDA says waiting

v0.5.1 binds presence to the Android foreground lifecycle.

```text
app resume
→ immediate ONLINE heartbeat
→ immediate active-task / offer poll
→ website refresh <= 3s

app pause/background
→ best-effort OFFLINE heartbeat + APP_BACKGROUND
→ if delivery fails, freshness TTL expires presence
```

The web UI treats `device_live=false` as authoritative and suppresses stale activity labels such as `WAITING_FOR_ORDER`.

## Failure: worker must keep tapping Camera

The ViewModel raises a one-shot camera request whenever a workflow enters a scan-required state. A manual close is respected until the workflow moves to another scan state. Camera, industrial scanner and manual test entry all continue through the same ScanBus validation path.
