# Deployment

## Production topology

FulfillOS production uses three layers:

- Vercel Services: Next.js control tower at `/` and FastAPI at `/api`.
- Neon Postgres: authoritative transactional store for orders, inventory, reservations, sessions and movements.
- MongoDB Atlas: telemetry/read-model store for device health, snapshots and analytics.

Postgres remains the system of record. Atlas must never be used as the authoritative inventory ledger.

## One-click production workflow

After adding the required GitHub Actions secrets, run:

`Actions → Deploy FulfillOS Production → Run workflow`

The workflow will:

1. Create/link the Vercel project `fulfillos` in the configured team if it does not exist.
2. Provision/connect a free Neon Postgres resource when missing.
3. Upsert production/preview environment variables into Vercel.
4. Build and deploy the Vercel Services bundle.
5. Verify `/api/health` and the web root.
6. Build Android debug + internal release APKs against the real production API URL.
7. Upload a `FulfillOS-v0.2.0-production-apks` artifact.

## Required GitHub Actions secrets

- `VERCEL_TOKEN`: create this in Vercel Account Settings → Tokens.
- `MONGODB_URI`: scoped Atlas SRV connection string for the FulfillOS telemetry database.
- `BOOTSTRAP_PICKER_PASSWORD`: initial picker password.
- `BOOTSTRAP_SUPERVISOR_PASSWORD`: initial supervisor password.

The Vercel team ID and project name are intentionally non-secret and are stored in the workflow.

## Vercel Services

The root `vercel.json` defines two services:

- `web` at `/`
- FastAPI `api` at `/api`

The Next.js app uses relative `/api` requests on Vercel. The Android production artifact is rebuilt after deployment with:

`FULFILLOS_API_BASE_URL=https://<production-host>/api`

## Database

Neon injects a standard `postgresql://` URL. The backend normalizes it to SQLAlchemy's psycopg v3 driver automatically.

For production evolution, schema changes should move to migrations before data models become incompatible. `Base.metadata.create_all` is still safe for the current additive bootstrap schema but is not a replacement for a migration system.

## Production users

Demo seeding is disabled by default. On first production start, the backend creates the configured bootstrap picker/supervisor if they do not already exist. Passwords are stored only as PBKDF2 hashes in Postgres.

## MongoDB Atlas

Atlas is best-effort telemetry only. The backend reuses a small serverless connection pool and treats Mongo write failures as non-blocking so an analytics outage cannot stop picking or inventory transactions.

The current Atlas deployment must allow Vercel's dynamic egress. If a paid static-egress setup is introduced later, narrow the Atlas network access list to those fixed addresses.
