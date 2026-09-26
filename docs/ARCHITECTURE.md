# Architecture

## Design goal

FulfillOS is an execution system, not a shopping catalog. Its most important job is to keep physical reality and digital state reconciled while workers move quickly through a noisy environment.

The primary consistency boundary is PostgreSQL.

```text
Customer order
    |
    v
Order / reservation engine -----> transactional outbox
    |                                  |
    v                                  v
Picking task --------------------> async events / analytics
    |
    +------ PDA local durable queue
    |         |
    |         +--- reconnect/replay with eventId
    |
    v
Inventory ledger -> stage -> handoff -> delivery integration

Supervisor web <---- read APIs / control tower snapshots
```

## Components

### PostgreSQL — source of truth

Stores:

- products and barcodes
- physical/logical locations
- inventory balances and immutable movements
- orders and reservations
- pick tasks and lines
- scan events
- device/associate state
- downtime attribution
- transactional outbox

Critical scan commits happen in one database transaction: validate task version → validate bin/item → consume reservation → decrement on-hand → append movement → append scan event → increment task version.

### Redis — optional

Useful for ephemeral presence, hot dashboard snapshots, rate limits, and low-value caches. Redis is never authoritative for stock.

### NATS JetStream — optional

Used by a long-running deployment for asynchronous integrations: notifications, analytics, read models and external delivery events. The database outbox is the bridge so DB state and event publication cannot silently diverge.

### MongoDB Atlas — optional secondary store

MongoDB can be useful for high-volume telemetry, device diagnostics, flexible event read models or archived operational documents. It is deliberately not required for the inventory transaction path.

### PDA Android app

Kotlin/Compose client with:

- local durable pending-event queue
- secure refresh credentials in Android Keystore
- reconnect + reconciliation
- scan adapter abstraction for industrial scanners
- server-confirmed pick progress
- explicit offline/recovery banners

### Vercel

The Next.js control tower and stateless FastAPI API can be deployed together with Vercel Services. For persistent consumers, WebSocket-heavy workloads or NATS workers, use a long-running container service alongside Vercel.
