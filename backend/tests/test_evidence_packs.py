from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZipFile

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from core.settings import settings
from db.models import Base, BenchmarkBatch, BenchmarkItem, Run
from reporting.evidence import build_batch_evidence_pack, build_run_evidence_pack


def _make_engine(tmp_path: Path) -> object:
    db_path = tmp_path / "evidence.db"
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


def test_run_evidence_pack_contains_manifest(tmp_path) -> None:
    # Isolate evidence output under tmp_path (restore global settings afterward).
    old_runs_dir = settings.runs_dir
    old_data_dir = settings.data_dir
    try:
        settings.runs_dir = tmp_path / "runs"
        settings.data_dir = tmp_path / "data"
        settings.runs_dir.mkdir(parents=True, exist_ok=True)
        settings.data_dir.mkdir(parents=True, exist_ok=True)

        engine = _make_engine(tmp_path)
        SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
        now = datetime.now(timezone.utc)

        with SessionLocal() as db:  # type: ignore[arg-type]
            db.add(Run(id="run_ev", scenario_id="urban_dusk", status="completed", stage="completed", progress=100, message="", error_message="", config_json="{}", created_at=now, updated_at=now, queued_at=now, started_at=now, finished_at=now))
            db.commit()

            out = build_run_evidence_pack(db, run_id="run_ev", include_frames=False)
            assert out.exists()

            with ZipFile(out) as zf:
                names = set(zf.namelist())
                assert "manifest.json" in names
                assert "run/run.json" in names
                manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
                assert "files" in manifest
    finally:
        settings.runs_dir = old_runs_dir
        settings.data_dir = old_data_dir


def test_batch_evidence_pack_contains_export_and_manifest(tmp_path) -> None:
    old_runs_dir = settings.runs_dir
    old_data_dir = settings.data_dir
    try:
        settings.runs_dir = tmp_path / "runs"
        settings.data_dir = tmp_path / "data"
        settings.runs_dir.mkdir(parents=True, exist_ok=True)
        settings.data_dir.mkdir(parents=True, exist_ok=True)

        engine = _make_engine(tmp_path)
        SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
        now = datetime.now(timezone.utc)

        with SessionLocal() as db:  # type: ignore[arg-type]
            db.add(BenchmarkBatch(id="batch_ev", name="ev", created_at=now, updated_at=now, status="processing", message="", config_json="{}", summary_json="{}"))
            db.add(Run(id="run_a", scenario_id="urban_dusk", status="completed", stage="completed", progress=100, message="", error_message="", config_json="{}", created_at=now, updated_at=now, queued_at=now, started_at=now, finished_at=now))
            db.add(BenchmarkItem(batch_id="batch_ev", scenario_id="urban_dusk", seed=1, stress_profile_json='{"id":"fog"}', run_id="run_a", status="completed", role="stressed", created_at=now))
            db.commit()

            out = build_batch_evidence_pack(db, batch_id="batch_ev")
            assert out.exists()
            with ZipFile(out) as zf:
                names = set(zf.namelist())
                assert "manifest.json" in names
                assert "batch/export.csv" in names
                assert "batch/batch.json" in names
    finally:
        settings.runs_dir = old_runs_dir
        settings.data_dir = old_data_dir
