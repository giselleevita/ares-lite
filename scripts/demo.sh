#!/usr/bin/env zsh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
VENV_DIR="$BACKEND_DIR/.venv"

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  echo "[demo] Backend virtualenv is missing. Run: make setup"
  exit 1
fi

cd "$BACKEND_DIR"
"$VENV_DIR/bin/python" -m demo
