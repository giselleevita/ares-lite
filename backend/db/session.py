from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timezone

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from core.settings import settings
from db.models import Base


connect_args: dict[str, object] = {}
if settings.database_url.startswith("sqlite"):
    # Allow DB access from the background worker thread.
    connect_args["check_same_thread"] = False
    # Fallback connect timeout (seconds); busy_timeout is set via PRAGMA below too.
    connect_args["timeout"] = 30

engine = create_engine(settings.database_url, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _sqlite_on_connect(dbapi_connection: object, _: object) -> None:
    if not settings.database_url.startswith("sqlite"):
        return
    cursor = dbapi_connection.cursor()
    # Improve concurrency characteristics for local/offline use.
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA synchronous=NORMAL;")
    cursor.execute("PRAGMA busy_timeout=5000;")
    cursor.close()


event.listen(engine, "connect", _sqlite_on_connect)


def _ensure_runs_columns() -> None:
    """Best-effort SQLite schema migration for the `runs` table.

    We intentionally keep this minimal to avoid adding migration tooling.
    """

    if not settings.database_url.startswith("sqlite"):
        return

    desired: list[tuple[str, str]] = [
        ("updated_at", "DATETIME"),
        ("queued_at", "DATETIME"),
        ("started_at", "DATETIME"),
        ("finished_at", "DATETIME"),
        ("locked_by", "VARCHAR(128)"),
        ("locked_at", "DATETIME"),
        ("attempts", "INTEGER DEFAULT 0"),
        ("cancel_requested", "INTEGER DEFAULT 0"),
        ("cancelled_at", "DATETIME"),
        ("stage", "VARCHAR(64)"),
        ("progress", "INTEGER"),
        ("message", "VARCHAR(256)"),
        ("error_message", "TEXT"),
    ]

    with engine.begin() as conn:
        rows = conn.execute(text("PRAGMA table_info(runs)")).fetchall()
        existing = {row[1] for row in rows}  # (cid, name, type, notnull, dflt_value, pk)

        for name, coltype in desired:
            if name in existing:
                continue
            conn.execute(text(f"ALTER TABLE runs ADD COLUMN {name} {coltype}"))

        # Backfill timestamps/status fields for pre-refactor databases.
        now = datetime.now(timezone.utc).isoformat()
        if "status" in existing and "stage" in {n for n, _ in desired}:
            conn.execute(
                text(
                    """
                    UPDATE runs
                    SET stage = COALESCE(NULLIF(stage, ''), status),
                        progress = COALESCE(progress, 0),
                        message = COALESCE(message, ''),
                        error_message = COALESCE(error_message, ''),
                        updated_at = COALESCE(updated_at, :now)
                    """
                ),
                {"now": now},
            )


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    _ensure_runs_columns()
    _ensure_benchmark_schema()
    _ensure_indexes()


def _ensure_indexes() -> None:
    if not settings.database_url.startswith("sqlite"):
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_detections_run_frame ON detections (run_id, frame_idx)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_runs_status_queued_at ON runs (status, queued_at, created_at)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_runs_status_locked_at ON runs (status, locked_at)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_benchmark_items_batch_created ON benchmark_items (batch_id, created_at)"
            )
        )


def _ensure_benchmark_schema() -> None:
    """Best-effort migration for benchmark batches/items tables."""
    if not settings.database_url.startswith("sqlite"):
        return

    with engine.begin() as conn:
        existing_tables = {
            row[0]
            for row in conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            ).fetchall()
        }

        # If we have a legacy table, migrate/copy into the new table.
        if "benchmark_suites" in existing_tables and "benchmark_batches" not in existing_tables:
            conn.execute(text("ALTER TABLE benchmark_suites RENAME TO benchmark_batches"))
            existing_tables.remove("benchmark_suites")
            existing_tables.add("benchmark_batches")
        elif "benchmark_suites" in existing_tables and "benchmark_batches" in existing_tables:
            # create_all may have already created the new table; copy rows forward best-effort.
            conn.execute(
                text(
                    """
                    INSERT OR IGNORE INTO benchmark_batches (id, name, created_at, updated_at, status, message, config_json)
                    SELECT id, name, created_at, updated_at, status, message, config_json
                    FROM benchmark_suites
                    """
                )
            )

        if "benchmark_batches" in existing_tables:
            cols = {row[1] for row in conn.execute(text("PRAGMA table_info(benchmark_batches)")).fetchall()}
            if "summary_json" not in cols:
                conn.execute(text("ALTER TABLE benchmark_batches ADD COLUMN summary_json TEXT DEFAULT '{}'"))

        if "benchmark_items" in existing_tables:
            cols = {row[1] for row in conn.execute(text("PRAGMA table_info(benchmark_items)")).fetchall()}
            if "batch_id" not in cols and "suite_id" in cols:
                conn.execute(text("ALTER TABLE benchmark_items ADD COLUMN batch_id VARCHAR(64)"))
                conn.execute(text("UPDATE benchmark_items SET batch_id = suite_id WHERE batch_id IS NULL"))
            elif "batch_id" in cols and "suite_id" in cols:
                conn.execute(text("UPDATE benchmark_items SET batch_id = suite_id WHERE (batch_id IS NULL OR batch_id = '')"))
            if "stress_profile_json" not in cols:
                conn.execute(text("ALTER TABLE benchmark_items ADD COLUMN stress_profile_json TEXT DEFAULT '{}'"))
                if "stress_profile_id" in cols:
                    conn.execute(
                        text(
                            "UPDATE benchmark_items "
                            "SET stress_profile_json = ('{\"id\": \"' || stress_profile_id || '\"}') "
                            "WHERE (stress_profile_json IS NULL OR stress_profile_json = '')"
                        )
                    )
            if "status" not in cols:
                conn.execute(text("ALTER TABLE benchmark_items ADD COLUMN status VARCHAR(32) DEFAULT 'queued'"))


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
