from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Event, Thread

from sqlalchemy import text

from core.settings import settings
from db.queue import (
    claim_next_run,
    count_runs_by_status,
    default_worker_id,
    recover_processing_runs,
)
from db.session import SessionLocal, engine
from db.runs import touch_run

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WorkerStats:
    worker_id: str
    lock_acquired: bool
    thread_alive: bool
    poll_interval: float
    last_claim_time: float | None
    claimed_count: int


_STOP = Event()
_WORKER: Thread | None = None
_LOCK_FILE: object | None = None
_LOCK_ACQUIRED = False
_WORKER_ID: str = default_worker_id()
_CLAIMED_COUNT = 0
_LAST_CLAIM_TIME: float | None = None


def _acquire_worker_lock() -> bool:
    """Acquire a cross-process lock so we start at most one worker per host."""
    global _LOCK_FILE, _LOCK_ACQUIRED
    if _LOCK_ACQUIRED:
        return True

    if not settings.worker_enabled:
        return False

    lock_path = Path(settings.worker_lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        handle = open(lock_path, "a+", encoding="utf-8")
    except Exception:
        logger.exception("Failed to open worker lock file: %s", lock_path)
        return False

    try:
        import fcntl  # type: ignore

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        handle.seek(0)
        handle.truncate()
        handle.write(f"pid={os.getpid()}\nworker_id={_WORKER_ID}\n")
        handle.flush()
        _LOCK_FILE = handle
        _LOCK_ACQUIRED = True
        return True
    except Exception:
        try:
            handle.close()
        except Exception:
            pass
        _LOCK_FILE = None
        _LOCK_ACQUIRED = False
        return False


def start_worker() -> None:
    global _WORKER
    if _WORKER is not None and _WORKER.is_alive():
        return

    if not _acquire_worker_lock():
        logger.info("ARES Lite worker not started (lock not acquired or worker disabled)")
        return

    # Recover stale processing runs from previous processes.
    # Also handle legacy runs that have status=processing but no lock metadata.
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE runs
                    SET status='queued',
                        stage='queued',
                        progress=0,
                        message='Recovered after restart',
                        updated_at=CURRENT_TIMESTAMP,
                        locked_by=NULL,
                        locked_at=NULL
                    WHERE status='processing' AND (locked_by IS NULL OR locked_at IS NULL)
                    """
                )
            )
    except Exception:
        logger.exception("Failed to recover orphaned processing runs")

    try:
        recover_processing_runs(
            engine,
            current_worker_id=_WORKER_ID,
            stale_after_seconds=int(settings.run_recover_stale_processing_seconds),
            mode=str(settings.run_recover_mode or "requeue").lower(),
        )
    except Exception:
        logger.exception("Run recovery failed during startup")

    _STOP.clear()
    _WORKER = Thread(target=_worker_loop, name="ares-lite-worker", daemon=True)
    _WORKER.start()
    logger.info("ARES Lite DB-backed worker started worker_id=%s", _WORKER_ID)


def stop_worker(timeout_sec: float = 2.0) -> None:
    _STOP.set()
    if _WORKER is None:
        return
    _WORKER.join(timeout=timeout_sec)


def _worker_loop() -> None:
    global _CLAIMED_COUNT, _LAST_CLAIM_TIME
    poll = float(settings.worker_poll_interval_sec or 0.5)
    poll = max(0.1, min(poll, 5.0))

    while not _STOP.is_set():
        run_id = None
        try:
            run_id = claim_next_run(engine, _WORKER_ID)
        except Exception:
            logger.exception("Failed to claim queued run")

        if not run_id:
            time.sleep(poll)
            continue

        _CLAIMED_COUNT += 1
        _LAST_CLAIM_TIME = time.time()

        try:
            from pipeline.orchestrator import execute_run_job  # noqa: WPS433

            execute_run_job(run_id)
        except Exception:
            logger.exception("Worker crashed during run execution run_id=%s", run_id)
            # Best-effort: ensure the run isn't left processing forever.
            try:
                with SessionLocal() as db:
                    touch_run(
                        db,
                        run_id,
                        status="failed",
                        stage="failed",
                        progress=100,
                        message="Failed",
                        error_message="Background worker crashed while executing job; see server logs.",
                        finished=True,
                    )
                    db.commit()
            except Exception:
                logger.exception("Failed to mark run failed after worker exception run_id=%s", run_id)


def worker_status() -> dict[str, object]:
    poll = float(settings.worker_poll_interval_sec or 0.5)
    return {
        "pid": os.getpid(),
        "worker_id": _WORKER_ID,
        "lock_acquired": _LOCK_ACQUIRED,
        "thread_alive": bool(_WORKER and _WORKER.is_alive()),
        "poll_interval": poll,
        "last_claim_time": _LAST_CLAIM_TIME,
        "claimed_count": _CLAIMED_COUNT,
        "queue_stats": count_runs_by_status(engine),
    }
