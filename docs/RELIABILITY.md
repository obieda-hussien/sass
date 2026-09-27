# Reliability design

## Failure: scan spinner after Wi-Fi drop

Bad behavior:

```text
request -> network disappears -> UI spins forever -> user opens another module to reset the client
```

FulfillOS behavior:

```text
persist local event -> timeout -> mark PENDING_SYNC -> network observer reconnects
-> refresh auth if needed -> batch sync -> reconcile snapshot
```

The screen explicitly distinguishes `Offline`, `Reconnecting`, `Pending sync`, and `Server confirmed`.

## Failure: client says 43 units, server says 42

FulfillOS never maintains an independent final counter. It maintains:

```text
attempted locally
pending acknowledgement
server-confirmed picked
```

The main completion counter uses only the last category.

## Failure: duplicate retry

Every stock-changing command contains an `event_id` unique constraint. Repeating it is read-after-write, not a second mutation.

## Failure: stale response rolls the user backward

- every task has `server_version`;
- every client event has `client_seq`;
- new, out-of-order sequences are rejected;
- retries of known event ids are accepted idempotently;
- conflict responses contain the authoritative snapshot;
- the PDA replaces stale projections instead of merging them heuristically.

## Failure: mid-order cancellation

A cancellation is an event and a state transition, not a disappearing task.

If nothing has been physically picked, cancellation may close the task.

If stock is already in the physical pick tote, the task becomes `RECOVERY_REQUIRED`. A worker must recover/stow those units explicitly. This preserves the physical/digital invariant.

If handoff already happened, the system switches to a return-required workflow rather than claiming the picked stock is back on a shelf.

## Failure: PDA reboot/logout

The server owns the active task. The client owns a durable journal of unacknowledged events. A reboot can destroy neither.

A secure refresh token is stored separately from the user's password and bound to the trusted device. Site policy may require an unlock/PIN/badge after reboot, but the system does not require the associate to reconstruct work state manually.

## SLA attribution

A single timer is insufficient. FulfillOS tracks wall time and accountable time.

```text
wall_elapsed
- approved network outage
- backend wait
- device recovery
- system exception
= effective associate elapsed
```

The observed local productivity board is represented by:

```text
target_minutes = ceil(2 * units / 3)
```

That policy is isolated in code so a site can replace it without changing the task engine.
