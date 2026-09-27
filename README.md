# FulfillOS

Clean-room micro-fulfillment execution system inspired by real warehouse workflows, without using proprietary source code, private endpoints, credentials, or brand assets.

This repository starts with the reliability layer first and now includes the v0.3 operations platform: inventory ledger, atomic one-picker/one-order dispatch, order/SPOO history, fulfillment-area controls, receiving/stow workflows, short/skip/damage automation, workforce state, attendance/payroll calculations, an Android PDA client, and a supervisor operations console.

## Why this exists

The core failure modes this design targets are:

- a scan appears locally but is not committed on the server;
- network loss leaves the picker UI hanging until the user manually reopens another tool;
- a PDA reboot or logout loses the active task;
- an order can be cancelled mid-pick without an explicit recovery flow;
- duplicate retries can increment inventory twice;
- stale snapshots can send a picker backwards in the order;
- SLA metrics can incorrectly charge technical downtime to the associate.

FulfillOS treats those as architectural problems, not UI bugs.

## Repository layout

```text
backend/      FastAPI reference backend + SQLAlchemy ledger + tests
web/          Next.js supervisor control tower
dashboard/    Zero-dependency control-tower fallback
android/      Kotlin/Jetpack Compose PDA client architecture
docs/         Domain, reliability, location grammar and workflow specs
infra/        Postgres/Redis/NATS local infrastructure
```

## Core invariants

1. **The server-authoritative inventory ledger is the source of truth.**
2. **Every inventory-changing client action has a globally unique event id.** Retrying the same event is safe.
3. **The PDA persists an event before transmitting it.** A reboot cannot make the client forget an unacknowledged scan.
4. **UI progress is server-confirmed progress.** Local attempts may be shown separately as `pending sync`.
5. **A cancelled picked order becomes a recovery task.** Picked goods do not magically teleport back to source bins.
6. **Task snapshots are versioned.** Out-of-order client sequences are rejected with an authoritative snapshot for reconciliation.
7. **System/network/device downtime is measured separately from associate active time.**

## Location examples

The parser currently supports examples such as:

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

`HAZ` and `HRV` are modeled as handling/security classifications layered over the physical fixture type, rather than pretending they are the same dimension as `A`, `X`, `H`, etc.

## Run the reference backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8080
```

Demo credentials:

```text
username: picker1
password: demo1234
device:   PDA-DEMO-001
```

Open `http://127.0.0.1:8080/dashboard` for the fallback supervisor view. Run the Next.js app for /operations (dispatch, holds, Order Explorer, inbound and metrics) and /people (workforce/payroll).

The default demo uses SQLite. Production should set `DATABASE_URL` to PostgreSQL and run schema migrations rather than `create_all`.

## Tests

```bash
cd backend
pytest -q
```

The first test suite covers location parsing, idempotent inventory movement, duplicate pick scans, sequence conflicts, mid-pick cancellation recovery, and downtime-aware SLA calculation.

## Current status

This is the first executable foundation, not the finished warehouse product. The next build slices are documented in `docs/ROADMAP.md`.


## Supervisor web control tower

The `web/` app is a Next.js control tower that consumes the compatibility read-model endpoint at `/v1/control-tower/summary`.

```bash
cd web
npm install
NEXT_PUBLIC_API_BASE_URL=http://localhost:8080 npm run dev
```

For Vercel Services, the web app is mounted at `/` and the FastAPI service at `/api`; see `vercel.json` and `docs/DEPLOYMENT.md`.

## v0.3 operations platform

- Hard one-picker / one-active-order database lease.
- Broadcast offers with atomic first-winner claims and supervisor direct assignment.
- Worker operational states block dispatch during break, receiving, stow, unpack, cycle count and similar work.
- Order Explorer by date/time, order id, picker username, full SPOO or SPOO suffix.
- Multi-bag SPOO close with full barcode storage and last-four picker summary.
- Warm-to-cold route sequencing plus FEFO-aware stock selection when expiry lots exist.
- Fulfillment holds at site/domain/zone/aisle/bin/SKU scope without falsifying physical inventory.
- Separate physical, fulfillable and blocked stock.
- Skip, short and damaged-item handling with repeated-short alerts and replenishment candidates.
- Shipment receiving, discrepancy reconciliation, cold-chain timers and stow recommendations.
- Shift clock-in/out with automatic late, early-leave, worked-time and overtime calculations.
- Explicit payroll deduction policy; performance metrics never change role or pay automatically.
- Demand-based slotting suggestions that require an operations decision.
- Web Operations Console and Android broadcast-offer / bag-completion flow.

See BUILD_REPORT.md, docs/WORKFLOWS.md and docs/ROADMAP.md for detail.
