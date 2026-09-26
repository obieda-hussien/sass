from __future__ import annotations

import math
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import DowntimeSegment, PickTask


def _utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def board_target_seconds(units: int) -> int:
    """Observed local board: ceil(2*units/3) minutes."""
    if units <= 0:
        return 0
    return math.ceil((2 * units) / 3) * 60


def effective_elapsed_seconds(db: Session, task: PickTask, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    start = task.started_at or task.accepted_at or task.offered_at
    if start is None:
        return 0
    elapsed = max(0, int((now - _utc(start)).total_seconds()))
    segments = db.scalars(select(DowntimeSegment).where(DowntimeSegment.task_id == task.id)).all()
    excluded = 0
    for seg in segments:
        end = _utc(seg.ended_at) if seg.ended_at else now
        excluded += max(0, int((end - _utc(seg.started_at)).total_seconds()))
    return max(0, elapsed - excluded)
