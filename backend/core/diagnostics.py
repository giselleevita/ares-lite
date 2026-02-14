from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from sqlalchemy.engine import make_url

from core.settings import settings


def _binary_version(binary: str) -> tuple[bool, str | None]:
    if shutil.which(binary) is None:
        return False, None
    try:
        proc = subprocess.run([binary, "-version"], capture_output=True, text=True, timeout=2)
    except Exception:
        return True, None
    if proc.returncode != 0:
        return True, None
    line = (proc.stdout or "").splitlines()[0].strip() if proc.stdout else None
    return True, line or None


def _dir_writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except Exception:
        return False


def _sqlite_db_path(database_url: str) -> Path | None:
    try:
        url = make_url(database_url)
    except Exception:
        return None
    if not str(url.drivername).startswith("sqlite"):
        return None
    if not url.database or url.database == ":memory:":
        return None
    path = Path(str(url.database))
    return path if path.is_absolute() else (Path.cwd() / path).resolve()


def _sqlite_wal_enabled() -> bool | None:
    if not settings.database_url.startswith("sqlite"):
        return None
    try:
        # Lazy import to avoid import-time side effects when this module is used outside the app.
        from db.session import engine  # noqa: WPS433

        with engine.connect() as conn:
            mode = conn.exec_driver_sql("PRAGMA journal_mode;").scalar()
        if mode is None:
            return None
        return str(mode).strip().lower() == "wal"
    except Exception:
        return None


def collect_health_diagnostics() -> dict[str, Any]:
    warnings: list[str] = []

    ffmpeg_ok, ffmpeg_version = _binary_version("ffmpeg")
    ffprobe_ok, _ffprobe_version = _binary_version("ffprobe")
    if not ffprobe_ok:
        warnings.append("ffprobe not found on PATH (required by frame extraction)")

    data_ok = _dir_writable(Path(settings.data_dir))
    runs_ok = _dir_writable(Path(settings.runs_dir))
    if not data_ok:
        warnings.append(f"data dir is not writable: {settings.data_dir}")
    if not runs_ok:
        warnings.append(f"runs dir is not writable: {settings.runs_dir}")

    db_path = _sqlite_db_path(settings.database_url)
    if settings.database_url.startswith("sqlite") and db_path is None:
        warnings.append("sqlite db_path could not be determined from DATABASE_URL")

    wal_enabled = _sqlite_wal_enabled()
    if wal_enabled is False:
        warnings.append("SQLite WAL mode is not enabled (expected WAL for concurrency)")

    # Warn-only: Python version.
    if sys.version_info < (3, 11):
        warnings.append(f"Python {sys.version.split()[0]} detected; recommended 3.11+")

    # Warn-only: disk space (conservative).
    try:
        free_bytes = shutil.disk_usage(str(settings.data_dir)).free
        if free_bytes < 1 * 1024 * 1024 * 1024:
            warnings.append(f"Low disk free space under data_dir: {free_bytes / (1024**3):.2f} GiB")
    except Exception:
        pass

    return {
        "ffmpeg_ok": bool(ffmpeg_ok),
        "ffmpeg_version": ffmpeg_version,
        "data_dir_writable": bool(data_ok and runs_ok),
        "db_path": str(db_path) if db_path else None,
        "sqlite_wal_enabled": wal_enabled,
        "warnings": warnings,
    }

