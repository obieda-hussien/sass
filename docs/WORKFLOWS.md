# Workflows

## Inbound / returns

```mermaid
flowchart LR
  A[Receive/return arrives] --> B[Scan item/container]
  B --> C{Temperature}
  C -->|Ambient| D[TSCRET001]
  C -->|Chilled| E[TSCRETCHL01]
  C -->|Frozen| F[TSCRETFRZ01]
  D --> G[Unpack complete]
  E --> G
  F --> G
  G --> H[BOH move]
  H --> I[Compatible final location]
  B -->|Damaged| J[DMG]
```

A BOH move is a first-class inventory movement with a unique event id. It is not a UI-only reassignment.

## Outbound picking

```mermaid
stateDiagram-v2
  [*] --> READY
  READY --> OFFERED
  OFFERED --> ACCEPTED
  ACCEPTED --> PICKING
  PICKING --> PICKED
  PICKED --> PACK_RACK
  PACK_RACK --> STAGED
  STAGED --> HANDOFF_READY
  HANDOFF_READY --> HANDED_OFF
  HANDED_OFF --> COMPLETED

  OFFERED --> CANCELLED
  ACCEPTED --> CANCELLED
  PICKING --> RECOVERY_REQUIRED: cancellation after physical pick
  PICKED --> RECOVERY_REQUIRED: cancellation
  STAGED --> RECOVERY_REQUIRED: cancellation
  HANDED_OFF --> RECOVERY_REQUIRED: return required
```

## Scan flow

```text
1. PDA creates UUID event id + monotonically increasing client sequence.
2. PDA writes the event to durable local storage.
3. PDA transmits the event.
4. Server validates bin/product/qty/task ownership/version.
5. Server commits inventory + task state atomically.
6. Server returns authoritative snapshot and event ACK.
7. PDA marks the local event ACKED and renders server-confirmed progress.
```

If step 3 or 6 fails, the exact same event id is retried. The server does not double-pick it.

## Reboot recovery

```text
Android process/device restarts
  -> session refresh from secure device-bound refresh credential
  -> fetch active task
  -> load local pending event journal
  -> sync events in client-sequence order
  -> receive authoritative snapshot
  -> reconcile UI
  -> resume
```

The user may still be asked to re-authenticate according to security policy, but task state cannot depend on the previous process staying alive.
