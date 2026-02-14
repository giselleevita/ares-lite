from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from db.models import Base, Run
from db.queue import claim_next_run, recover_processing_runs


def _make_engine(tmp_path) -> object:
    db_path = tmp_path / "queue.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        future=True,
        connect_args={"check_same_thread": False, "timeout": 30},
    )

    def _on_connect(dbapi_connection, _):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA synchronous=NORMAL;")
        cursor.execute("PRAGMA busy_timeout=5000;")
        cursor.close()

    event.listen(engine, "connect", _on_connect)
    Base.metadata.create_all(bind=engine)
    return engine


def test_claim_next_run_atomic(tmp_path) -> None:
    engine = _make_engine(tmp_path)
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    run_id = "run_test_claim"
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:  # type: ignore[arg-type]
        db.add(
            Run(
                id=run_id,
                scenario_id="urban_dusk",
                status="queued",
                stage="queued",
                queued_at=now,
                updated_at=now,
                config_json="{}",
            )
        )
        db.commit()

    barrier = threading.Barrier(2)
    results: list[str | None] = [None, None]

    def _claimer(idx: int) -> None:
        barrier.wait()
        results[idx] = claim_next_run(engine, worker_id=f"worker_{idx}")  # type: ignore[arg-type]

    t1 = threading.Thread(target=_claimer, args=(0,))
    t2 = threading.Thread(target=_claimer, args=(1,))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert results.count(run_id) == 1
    assert results.count(None) == 1

    with SessionLocal() as db:  # type: ignore[arg-type]
        row = db.query(Run).filter(Run.id == run_id).first()
        assert row is not None
        assert row.status == "processing"
        assert row.locked_by is not None
        assert row.locked_at is not None
        assert row.attempts >= 1


def test_recover_processing_runs_requeue(tmp_path) -> None:
    engine = _make_engine(tmp_path)
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    run_id = "run_test_recover"
    now = datetime.now(timezone.utc)
    old = now - timedelta(hours=10)

    with SessionLocal() as db:  # type: ignore[arg-type]
        db.add(
            Run(
                id=run_id,
                scenario_id="urban_dusk",
                status="processing",
                stage="extracting_frames",
                queued_at=now,
                started_at=old,
                updated_at=old,
                locked_by="other_worker",
                locked_at=old,
                attempts=1,
                config_json="{}",
            )
        )
        db.commit()

    affected = recover_processing_runs(
        engine,  # type: ignore[arg-type]
        current_worker_id="current_worker",
        stale_after_seconds=60,
        mode="requeue",
    )
    assert affected == 1

    with SessionLocal() as db:  # type: ignore[arg-type]
        row = db.query(Run).filter(Run.id == run_id).first()
        assert row is not None
        assert row.status == "queued"
        assert row.locked_by is None
        assert row.locked_at is None


def test_claim_next_run_skips_cancel_requested(tmp_path) -> None:
    engine = _make_engine(tmp_path)
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    now = datetime.now(timezone.utc)
    with SessionLocal() as db:  # type: ignore[arg-type]
        db.add(
            Run(
                id="run_cancel_queued",
                scenario_id="urban_dusk",
                status="queued",
                stage="queued",
                queued_at=now,
                updated_at=now,
                cancel_requested=True,
                config_json="{}",
            )
        )
        db.commit()

    claimed = claim_next_run(engine, worker_id="worker_a")  # type: ignore[arg-type]
    assert claimed is None
