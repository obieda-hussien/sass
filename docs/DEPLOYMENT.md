# FulfillOS deployment — v0.5

## Production topology

FulfillOS production uses:

- **Vercel Services** — Next.js web at `/` and FastAPI under `/api`;
- **Neon PostgreSQL** — authoritative transactional store;
- **MongoDB Atlas** — best-effort telemetry/read-model store;
- **GitHub Actions** — CI, production deployment and Android artifacts.

Production:

```text
https://fulfillos-nine.vercel.app
https://fulfillos-nine.vercel.app/api
```

PostgreSQL remains the system of record for inventory, orders, sessions, workforce/payroll, replenishment and operational state.

## Production workflow

The `Deploy FulfillOS Production` workflow runs on `main` changes that affect the deployable application and can also be started manually.

It performs:

1. checkout;
2. Node/Vercel CLI setup;
3. required-secret validation;
4. Vercel project linking/configuration;
5. Neon provisioning/linking when required;
6. production/preview environment synchronization;
7. Vercel production deploy;
8. route inspection;
9. public `/api/health` verification;
10. web-root verification;
11. Java/Gradle setup;
12. Android debug + release assembly against the real production API;
13. Android version extraction from Gradle;
14. versioned APK artifact preparation;
15. SHA-256 checksum generation;
16. artifact upload.

## Required GitHub Actions secrets

```text
VERCEL_TOKEN
MONGODB_URI
BOOTSTRAP_PICKER_PASSWORD
BOOTSTRAP_SUPERVISOR_PASSWORD
```

The workflow fails early when any required secret is missing.

## Production environment

Important variables synchronized by the deployment workflow include:

```text
MONGODB_URI
MONGODB_DATABASE=fulfillos_telemetry
DEMO_SEED=0
ACCESS_TOKEN_MINUTES=30
REFRESH_TOKEN_DAYS=14
BOOTSTRAP_PICKER_USERNAME=picker
BOOTSTRAP_PICKER_PASSWORD=<secret>
BOOTSTRAP_SUPERVISOR_USERNAME=supervisor
BOOTSTRAP_SUPERVISOR_PASSWORD=<secret>
```

Bootstrap accounts are for initial/recovery access. Normal employee/user management should be performed through the application.

## v0.5 runtime/eventing configuration

Optional server-side environment variables:

```text
FULFILLOS_OUTBOX_INTERVAL_SECONDS=2
FULFILLOS_INCIDENT_WEBHOOK_URL=
OTEL_SERVICE_NAME=fulfillos-api
OTEL_EXPORTER_OTLP_ENDPOINT=
FULFILLOS_SERVER_API_BASE_URL=https://<api-host>/api
```

- The outbox interval controls background publication cadence.
- The incident webhook receives `incident.*` outbox topics when configured.
- OTLP export is optional; structured request logging and in-process instrumentation still work without an exporter.
- `FULFILLOS_SERVER_API_BASE_URL` is used by the Next.js BFF when web and API origins differ. Do not expose bearer credentials through public environment variables.

## Health verification

The deployment workflow validates that:

```json
{
  "ok": true,
  "version": "0.5.1",
  "database": "connected",
  "telemetry": "connected"
}
```

and verifies the public web root.

This prevents a deploy from being considered successful merely because the platform accepted the build.

## Database migrations

### Alembic

Alembic is the forward schema mechanism. v0.5 adds identity-lifecycle and transactional-outbox revisions on top of the v0.4 governance schema.

Files:

```text
backend/alembic.ini
backend/alembic/env.py
backend/alembic/versions/
backend/app/schema_migrations.py
```

Startup behavior:

### Existing pre-Alembic production database

```text
detect existing core schema
→ acquire PostgreSQL advisory lock
→ stamp verified baseline revision
→ upgrade to Alembic head
→ release lock
```

### Fresh database

```text
detect missing core schema
→ acquire PostgreSQL advisory lock
→ create current metadata
→ stamp current head
→ release lock
```

Future schema changes should be represented as Alembic revisions instead of relying on `Base.metadata.create_all` as the normal upgrade mechanism.

### Disable automatic migration

Automatic startup migration can be disabled intentionally with:

```text
FULFILLOS_DISABLE_AUTO_MIGRATE=1
```

Use this only when the deployment process runs migrations separately.

### v0.5 migrations

The v0.5 migration chain includes:

- PDA presence / telemetry support;
- user `must_change_password` + `deleted_at`;
- transactional `outbox_events`;
- case-insensitive unique username index on `lower(username)`.

Deployments must allow the startup migrator to reach the current Alembic head before serving normal workload.

## Historical SQL migrations

These remain in the repository as historical/bootstrap references:

```text
backend/migrations/0001_initial.sql
backend/migrations/0002_ops_platform.sql
```

They are not the preferred forward migration path after the Alembic baseline.

## Browser manager session security

v0.5 manager authentication uses the Next.js BFF:

- access/refresh credentials are `HttpOnly`;
- cookies use `SameSite=Strict` and `Secure` in production;
- unsafe mutations require CSRF validation;
- browser JavaScript never reads the FastAPI bearer credential;
- server-side refresh rotates the web session when needed.

Production should terminate TLS at the hosting layer and preserve same-site cookie behavior for the web/BFF origin.

## Android production build

Current Android release metadata:

```text
versionName = 0.5.1
versionCode = 7
minSdk = 26
targetSdk = 36
compileSdk = 37
```

Release builds require:

```text
FULFILLOS_API_BASE_URL=https://<production-host>/api
```

The build fails if the release URL is absent or non-HTTPS.

The deployment workflow builds both:

- debug APK;
- internal release APK.

## Android artifact names

Artifact labels are derived from Gradle `versionName` instead of being hard-coded.

Example:

```text
FulfillOS-v0.5.1-production-apks
  ├─ FulfillOS-v0.5.1-prod-debug.apk
  ├─ FulfillOS-v0.5.1-prod-release.apk
  ├─ production-url.txt
  └─ SHA256SUMS.txt
```

This prevents release metadata and artifact names from drifting apart.

## Signing

Current release APKs still use the debug signing configuration for internal installation/testing.

Before store/public distribution:

1. create/protect a production signing key or use Play App Signing;
2. store signing material outside the repository;
3. configure CI with protected secrets;
4. validate certificate continuity;
5. introduce versioned release/changelog/rollback policy.

## MongoDB Atlas

Atlas is non-authoritative telemetry.

A telemetry failure must not block:

- picking;
- inventory movement;
- replenishment;
- payroll/workforce commands;
- order completion.

The current deployment supports Vercel dynamic egress. If a future paid/static-egress setup is introduced, narrow Atlas network access accordingly.

## Rollback considerations

Application rollback and schema rollback are separate decisions.

For production incidents:

- prefer rolling application code forward/fixing forward when the new schema is backward compatible;
- do not destructively downgrade warehouse/payroll data without an explicit migration review;
- preserve inventory/audit/replenishment event history;
- verify `/api/health` after rollback;
- verify Android API compatibility before distributing an older APK.

## Deployment checklist

Before a production merge:

- backend tests green;
- web build green;
- Android debug/release build green;
- Alembic revision reviewed when schema changes exist;
- release version updated when behavior changes;
- no committed secrets;
- production API remains HTTPS-only;
- migration path is safe for existing Neon data;
- sensitive workforce changes remain permission-gated/audited.
