#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
VENV_DIR="$BACKEND_DIR/.venv"

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  echo "[demo] Backend virtualenv is missing. Run: make setup"
  exit 1
fi

if [[ ! -x "$VENV_DIR/bin/uvicorn" ]]; then
  echo "[demo] Backend uvicorn is missing. Run: make setup"
  exit 1
fi

if [[ ! -d "$FRONTEND_DIR/node_modules" ]]; then
  echo "[demo] Frontend dependencies are missing. Run: make setup"
  exit 1
fi

echo "[demo] Running doctor..."
"$VENV_DIR/bin/python" "$ROOT_DIR/scripts/doctor.py"

echo "[demo] Ensuring golden demo assets exist..."
"$VENV_DIR/bin/python" -c "import sys; from pathlib import Path; repo=Path('$ROOT_DIR'); sys.path.insert(0, str(repo/'backend')); from pipeline.demo_assets import ensure_golden_demo_assets; ensure_golden_demo_assets(repo/'backend'/'data'); print('[demo] demo assets ready')"

echo ""
echo "[demo] Starting backend + frontend dev servers..."
echo "[demo] UI:     http://127.0.0.1:5173"
echo "[demo] Backend: http://127.0.0.1:8000/health"
echo ""
echo "[demo] Instructions:"
echo "1) Open the UI URL"
echo "2) Click 'Run Demo' (fixed seed, reproducible)"
echo "3) Explore blind spots + readiness breakdown"
echo ""

cleanup() {
  if [[ -n "${BACKEND_PID:-}" ]]; then
    kill "$BACKEND_PID" 2>/dev/null || true
  fi
  if [[ -n "${FRONTEND_PID:-}" ]]; then
    kill "$FRONTEND_PID" 2>/dev/null || true
  fi
}

trap cleanup EXIT INT TERM

cd "$BACKEND_DIR"
"$VENV_DIR/bin/uvicorn" main:app --reload --host 127.0.0.1 --port 8000 &
BACKEND_PID=$!

cd "$FRONTEND_DIR"
npm run dev -- --host 127.0.0.1 --port 5173 &
FRONTEND_PID=$!

wait "$BACKEND_PID" "$FRONTEND_PID"
