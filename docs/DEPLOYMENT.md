# Deployment

## Vercel Services

The root `vercel.json` defines two services:

- `web` at `/`
- FastAPI `api` at `/api`

Configure at minimum:

- `DATABASE_URL`
- `ACCESS_TOKEN_MINUTES`
- `REFRESH_TOKEN_DAYS`

The Next.js app uses relative `/api` requests on Vercel and `NEXT_PUBLIC_API_BASE_URL` for local development.

## Database

Use managed PostgreSQL for production. PostgreSQL remains the authoritative transaction store for inventory, reservations, tasks and audit movements.

Run migrations before promotion. Do not use request startup as the production schema-migration mechanism.

## Long-running workers

Redis and NATS remain optional infrastructure for cache/event processing. Long-running consumers should use a container/runtime suited to persistent workers rather than request-bound serverless execution.

## MongoDB Atlas

Atlas is optional and should be used only for telemetry, analytics or denormalized read models unless the architecture is intentionally changed. It is not the authoritative inventory ledger.
