from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from db.models import Run


def is_cancel_requested(db: Session, run_id: str) -> bool:
    value = db.query(Run.cancel_requested).filter(Run.id == run_id).scalar()
    return bool(value)


def request_cancel(db: Session, run_id: str) -> None:
    run = db.query(Run).filter(Run.id == run_id).first()
    if run is None:
        return
    now = datetime.now(timezone.utc)
    run.updated_at = now
    run.cancel_requested = True
    run.message = "Cancellation requested"
    db.add(run)


def mark_cancelled(db: Session, run_id: str, *, message: str = "Cancelled") -> None:
    run = db.query(Run).filter(Run.id == run_id).first()
    if run is None:
        return
    now = datetime.now(timezone.utc)
    run.updated_at = now
    run.finished_at = run.finished_at or now
    run.cancelled_at = run.cancelled_at or now
    run.status = "cancelled"
    run.stage = "cancelled"
    run.progress = 100
    run.message = message
    run.error_message = ""
    run.locked_by = None
    run.locked_at = None
    db.add(run)


def touch_run(
    db: Session,
    run_id: str,
    *,
    status: str | None = None,
    stage: str | None = None,
    progress: int | None = None,
    message: str | None = None,
    error_message: str | None = None,
    config_json: str | None = None,
    started: bool = False,
    finished: bool = False,
) -> None:
    run = db.query(Run).filter(Run.id == run_id).first()
    if run is None:
        return

    now = datetime.now(timezone.utc)
    run.updated_at = now

    if status is not None:
        run.status = status
    if stage is not None:
        run.stage = stage
    if progress is not None:
        run.progress = max(0, min(100, int(progress)))
    if message is not None:
        run.message = str(message)
    if error_message is not None:
        run.error_message = str(error_message)
    if config_json is not None:
        run.config_json = config_json

    if started and run.started_at is None:
        run.started_at = now
    if finished and run.finished_at is None:
        run.finished_at = now

    db.add(run)


def safe_json(obj: Any) -> str:
    import json

    return json.dumps(obj, ensure_ascii=True)
