# Reliability contract

The warehouse floor is treated as an unreliable network environment.

## Scan protocol

Every mutating scan contains:

- `event_id` — globally unique idempotency key
- `client_sequence` — monotonic sequence within a task
- `client_task_version` — optimistic concurrency token
- `task_line_id`
- associate/device identity
- scanned bin
- scanned barcode
- quantity

A successful response returns the new server task version.

If the response is lost, the PDA keeps the event in durable local storage and calls reconcile. If the event already committed, it is marked complete locally. If not, it is replayed with the same event ID.

## Why this prevents "43 scans on PDA, 42 on server"

The final counter shown as completed is derived from **committed task lines returned by the server**, not a local increment animation. The UI may display a temporary "syncing 1 scan" indicator, but it cannot claim the item is committed until acknowledged.

## Cancellation

Cancellation is never deletion.

- no committed picks → release reservations → `CANCELLED`
- one or more committed picks → release unpicked reservations → `RECOVERY_REQUIRED`

The already-picked physical units remain represented in the ledger and the supervisor receives a recovery exception instead of silently losing the task.

## PDA restart/logout

The task belongs to server state, not process memory.

After startup:

1. secure session refresh / explicit re-auth if policy requires it
2. send device heartbeat
3. call `/v1/sync/reconcile`
4. restore active task from server
5. resolve committed local pending IDs
6. replay only unknown events

## SLA attribution

Track wall time and attributable downtime separately:

- associate active time
- network offline
- device recovery
- system exception
- explicit break/other activity

Supervisor metrics should never label infrastructure downtime as associate picking delay.
