# Deployment

## Vercel

The root `vercel.json` uses Vercel Services:

- `web` at `/`
- FastAPI `api` at `/api`

Required project variables:

- `DATABASE_URL`
- `FULFILLOS_JWT_SECRET`
- `CORS_ORIGINS`

Optional:

- `MONGODB_URI`
- `MONGODB_DATABASE`
- `REDIS_URL`
- `NATS_URL`

For the Vercel project, select the **Services** framework preset.

## Database

Use a managed PostgreSQL database for production. Apply migrations before promotion and never run destructive schema operations from request startup.

The current development build can create tables automatically for local testing; production migration tooling will replace this before v1.0.

## Long-running workers

Vercel is appropriate for the stateless control plane. NATS consumers/outbox publishers should run as a long-lived container service when enabled.

## MongoDB Atlas

Atlas is optional. If enabled, use it for telemetry/read models rather than authoritative stock. A separate database user should receive only the roles needed by the telemetry collection.
