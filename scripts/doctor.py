#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def _fmt_bool(ok: bool | None) -> str:
    if ok is True:
        return "OK"
    if ok is False:
        return "FAIL"
    return "n/a"


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]

    # Align relative SQLite paths with how the backend is typically run (cwd=backend).
    backend_dir = repo_root / "backend"
    os.chdir(backend_dir)
    sys.path.insert(0, str(backend_dir))

    from core.diagnostics import collect_health_diagnostics  # noqa: E402

    diag = collect_health_diagnostics()
    warnings = diag.get("warnings") if isinstance(diag, dict) else []
    warnings = warnings if isinstance(warnings, list) else []

    now = datetime.now(timezone.utc).isoformat()
    print(f"ARES Lite doctor ({now})")
    print("")

    ffmpeg_ok = bool(diag.get("ffmpeg_ok"))
    print(f"ffmpeg:        {_fmt_bool(ffmpeg_ok)}")
    if diag.get("ffmpeg_version"):
        print(f"  version:     {diag.get('ffmpeg_version')}")

    data_ok = bool(diag.get("data_dir_writable"))
    print(f"data writable: {_fmt_bool(data_ok)}")

    db_path = diag.get("db_path")
    print(f"db path:       {db_path if db_path else 'n/a'}")
    wal = diag.get("sqlite_wal_enabled")
    print(f"sqlite WAL:    {_fmt_bool(wal)}")

    if warnings:
        print("")
        print("Warnings:")
        for item in warnings:
            print(f"- {item}")

    # Exit non-zero only for hard blockers for running demos/selfcheck.
    hard_fail = []
    if not ffmpeg_ok:
        hard_fail.append("ffmpeg missing")
    if not data_ok:
        hard_fail.append("data/runs not writable")

    if hard_fail:
        print("")
        print("Doctor status: FAIL")
        for item in hard_fail:
            print(f"- {item}")
        return 1

    print("")
    print("Doctor status: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

