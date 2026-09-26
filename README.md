# FulfillOS

FulfillOS is a **clean-room micro-fulfillment execution platform** for fast grocery / dark-store operations.

It is designed around the failure modes that matter on a real warehouse floor: flaky Wi-Fi, PDA restarts, duplicated scans, cancelled orders in the middle of a pick, inventory drift, temperature-aware storage, damage/quarantine, and the need to distinguish associate delay from system delay.

> This project is built from first principles and public warehouse concepts. It does not contain copied proprietary source code, private APIs, credentials, internal assets, or vendor branding.

## Monorepo

- `backend/` — FastAPI transactional execution API.
- `web/` — Next.js control tower for supervisors.
- `android/` — Kotlin + Jetpack Compose PDA client.
- `docs/` — architecture, workflows, location grammar and reliability contracts.
- `infra/` — local PostgreSQL / Redis / NATS stack.
- `vercel.json` — Vercel Services configuration for the web control tower + API.

## Reliability invariants

1. **Server-confirmed progress only.** A scan does not advance final progress until the server commits it.
2. **Every mutating command has an idempotency key.** Replays are safe.
3. **Inventory is a ledger, not a counter.** Every quantity change has an auditable movement.
4. **Task state is versioned.** Stale clients cannot silently overwrite newer server state.
5. **Cancellation is a state transition, never disappearance.** Mid-pick cancellation enters recovery.
6. **Device restart is expected.** Re-auth + reconcile resumes from the last committed server state.
7. **SLA attribution is explicit.** Network, device and system downtime are separated from associate active time.

## Location model

FulfillOS models physical and logical locations independently:

- `A` ambient shelving
- `V` produce
- `D` bulk/liquids
- `X` drawers
- `H` hanging/pegboard
- `T` special metal shelving
- `R` bagged snacks/chips
- `C` chilled
- `F` frozen
- `HAZ` hazardous handling class layered over fixture type
- `HRV` high-value
- `TSCRET001`, `TSCRETCHL01`, `TSCRETFRZ01` temporary unpack locations
- `DMG` damaged/quarantine
- `SPECIAL` exception holding

Example: `P-1-A115E181` → floor P-1, ambient fixture A, aisle 115, level E, slot 181.

## Local development

```bash
cp .env.example .env
docker compose -f infra/docker-compose.yml up -d

cd backend
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
pytest
uvicorn app.main:app --reload --port 8000
```

In another shell:

```bash
cd web
npm install
npm run dev
```

The web app calls the API through `/api` in Vercel and through `NEXT_PUBLIC_API_BASE_URL` locally.

## Cloud direction

- **Vercel**: excellent fit for the Next.js control tower and a stateless FastAPI service through Vercel Services.
- **PostgreSQL**: primary source of truth for inventory, reservations, pick commits, task versions and audit movements.
- **Redis / NATS**: optional low-latency cache + event transport for a long-running worker deployment.
- **MongoDB Atlas**: optional secondary document/event read model; not required as the primary transactional store.

See `docs/ARCHITECTURE.md` and `docs/RELIABILITY.md`.
