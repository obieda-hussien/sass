from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models_ops import OutboxEvent
from ..telemetry import emit as emit_telemetry


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def enqueue_outbox(
    db: Session,
    *,
    topic: str,
    aggregate_type: str,
    aggregate_id: str,
    payload: dict[str, Any],
) -> OutboxEvent:
    """Persist an integration event in the caller's existing transaction."""
    event = OutboxEvent(
        topic=topic.strip(),
        aggregate_type=aggregate_type.strip().upper(),
        aggregate_id=str(aggregate_id),
        payload_json=json.dumps(payload, separators=(",", ":"), sort_keys=True, default=str),
    )
    db.add(event)
    db.flush()
    return event


def _incident_webhook(event: OutboxEvent, payload: dict[str, Any]) -> tuple[bool, str | None]:
    url = os.getenv("FULFILLOS_INCIDENT_WEBHOOK_URL", "").strip()
    if not url or not event.topic.startswith("incident."):
        return True, None
    try:
        response = httpx.post(
            url,
            json={
                "event_id": event.id,
                "topic": event.topic,
                "aggregate_type": event.aggregate_type,
                "aggregate_id": event.aggregate_id,
                "payload": payload,
                "occurred_at": event.created_at.isoformat(),
            },
            timeout=5.0,
        )
        response.raise_for_status()
        return True, None
    except Exception as exc:
        return False, f"incident webhook: {exc}"[:480]


def dispatch_outbox_once(limit: int = 50) -> dict[str, int]:
    """Best-effort external distribution with DB-backed retry.

    The outbox row is created atomically with the business transaction. This
    dispatcher can run in multiple processes: PostgreSQL SKIP LOCKED prevents
    two warm instances from publishing the same batch simultaneously.
    """
    sent = failed = 0
    db = SessionLocal()
    try:
        with db.begin():
            query = (
                select(OutboxEvent)
                .where(
                    OutboxEvent.status.in_(["PENDING", "RETRY"]),
                    OutboxEvent.available_at <= now_utc(),
                )
                .order_by(OutboxEvent.created_at)
                .limit(max(1, min(limit, 200)))
            )
            if db.bind is not None and db.bind.dialect.name == "postgresql":
                query = query.with_for_update(skip_locked=True)
            rows = db.scalars(query).all()

            telemetry_configured = bool(os.getenv("MONGODB_URI", "").strip())
            for event in rows:
                event.attempts += 1
                payload = json.loads(event.payload_json or "{}")
                telemetry_ok = True
                telemetry_error = None
                if telemetry_configured:
                    telemetry_ok = emit_telemetry(
                        "event_stream",
                        {
                            "event_id": event.id,
                            "topic": event.topic,
                            "aggregate_type": event.aggregate_type,
                            "aggregate_id": event.aggregate_id,
                            "payload": payload,
                            "created_at": event.created_at,
                        },
                    )
                    if not telemetry_ok:
                        telemetry_error = "telemetry sink unavailable"

                webhook_ok, webhook_error = _incident_webhook(event, payload)
                if telemetry_ok and webhook_ok:
                    event.status = "PUBLISHED"
                    event.published_at = now_utc()
                    event.last_error = None
                    sent += 1
                else:
                    failed += 1
                    event.status = "FAILED" if event.attempts >= 20 else "RETRY"
                    delay_seconds = min(300, 2 ** min(event.attempts, 8))
                    event.available_at = now_utc() + timedelta(seconds=delay_seconds)
                    event.last_error = "; ".join(
                        value for value in [telemetry_error, webhook_error] if value
                    )[:500]
        return {"published": sent, "failed": failed}
    finally:
        db.close()


async def outbox_dispatch_loop(stop_event: asyncio.Event, interval_seconds: float = 2.0) -> None:
    while not stop_event.is_set():
        try:
            await asyncio.to_thread(dispatch_outbox_once)
        except Exception:
            # Distribution failure must never terminate the API process or alter
            # the already committed warehouse transaction.
            pass
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        except asyncio.TimeoutError:
            pass


def outbox_health(db: Session) -> dict[str, int]:
    rows = db.execute(
        select(OutboxEvent.status, func.count())
        .group_by(OutboxEvent.status)
    ).all()
    counts = {str(status): int(count) for status, count in rows}
    return {
        "pending": counts.get("PENDING", 0) + counts.get("RETRY", 0),
        "published": counts.get("PUBLISHED", 0),
        "failed": counts.get("FAILED", 0),
    }
