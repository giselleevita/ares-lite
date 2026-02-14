from __future__ import annotations

import socket
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Engine, text


def default_worker_id() -> str:
    host = socket.gethostname()
    suffix = uuid.uuid4().hex[:8]
    import os

    return f"{host}:{os.getpid()}:{suffix}"


def claim_next_run(engine: Engine, worker_id: str) -> str | None:
    """Atomically claim the next queued run.

    SQLite has limited concurrency; we use BEGIN IMMEDIATE to ensure only one
    worker can claim a run at a time.
    """

    for _ in range(5):
        with engine.connect() as conn:
            conn.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    text(
                        """
                        SELECT id
                        FROM runs
                        WHERE status = 'queued' AND COALESCE(cancel_requested, 0) = 0
                        ORDER BY
                          COALESCE(queued_at, created_at) ASC,
                          created_at ASC
                        LIMIT 1
                        """
                    )
                ).fetchone()
                if row is None:
                    conn.exec_driver_sql("COMMIT")
                    return None

                run_id = str(row[0])
                now = datetime.now(timezone.utc)
                result = conn.execute(
                    text(
                        """
                        UPDATE runs
                        SET status = 'processing',
                            locked_by = :worker_id,
                            locked_at = :now,
                            attempts = COALESCE(attempts, 0) + 1,
                            updated_at = :now,
                            started_at = COALESCE(started_at, :now),
                            message = 'Claimed by worker'
                        WHERE id = :run_id
                          AND status = 'queued'
                          AND COALESCE(cancel_requested, 0) = 0
                        """
                    ),
                    {"worker_id": worker_id, "now": now, "run_id": run_id},
                )
                if result.rowcount == 1:
                    conn.exec_driver_sql("COMMIT")
                    return run_id

                conn.exec_driver_sql("ROLLBACK")
            except Exception:
                conn.exec_driver_sql("ROLLBACK")
                raise

        time.sleep(0.02)

    return None


def recover_processing_runs(
    engine: Engine,
    *,
    current_worker_id: str,
    stale_after_seconds: int,
    mode: str,
) -> int:
    """Recover stale processing runs from other workers.

    mode: 'requeue' or 'fail'
    Returns number of runs affected.
    """

    if stale_after_seconds <= 0:
        return 0

    now = datetime.now(timezone.utc)
    cutoff = datetime.fromtimestamp(now.timestamp() - stale_after_seconds, tz=timezone.utc)

    with engine.begin() as conn:
        if mode == "fail":
            result = conn.execute(
                text(
                    """
                    UPDATE runs
                    SET status = 'failed',
                        stage = 'failed',
                        progress = 100,
                        message = 'Failed (stale processing run recovered on startup)',
                        error_message = 'Run was left processing for too long; marked failed during recovery.',
                        finished_at = COALESCE(finished_at, :now),
                        updated_at = :now,
                        locked_by = NULL,
                        locked_at = NULL
                    WHERE status = 'processing'
                      AND locked_by IS NOT NULL
                      AND locked_by != :current_worker_id
                      AND locked_at IS NOT NULL
                      AND locked_at < :cutoff
                    """
                ),
                {"now": now, "cutoff": cutoff, "current_worker_id": current_worker_id},
            )
            return int(result.rowcount or 0)

        # default: requeue
        result = conn.execute(
            text(
                """
                UPDATE runs
                SET status = 'queued',
                    stage = 'queued',
                    progress = 0,
                    message = 'Recovered after restart',
                    updated_at = :now,
                    locked_by = NULL,
                    locked_at = NULL
                WHERE status = 'processing'
                  AND locked_by IS NOT NULL
                  AND locked_by != :current_worker_id
                  AND locked_at IS NOT NULL
                  AND locked_at < :cutoff
            """
        ),
            {"now": now, "cutoff": cutoff, "current_worker_id": current_worker_id},
        )
        return int(result.rowcount or 0)


def count_runs_by_status(engine: Engine) -> dict[str, int]:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT status, COUNT(*) FROM runs GROUP BY status")
        ).fetchall()
    out: dict[str, int] = {}
    for status, count in rows:
        out[str(status)] = int(count)
    return out
