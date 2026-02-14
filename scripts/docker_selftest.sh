#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE_FILE="$ROOT_DIR/docker/docker-compose.yml"

KEEP_VOLUMES="${KEEP_VOLUMES:-0}"
TIMEOUT_SEC="${TIMEOUT_SEC:-180}"
POLL_INTERVAL_SEC="${POLL_INTERVAL_SEC:-1}"

UI_BASE="http://127.0.0.1:5173"

if ! command -v docker >/dev/null 2>&1; then
  echo "[docker-selftest] docker is not installed or not on PATH"
  exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
  echo "[docker-selftest] docker compose is not available (need Docker Compose v2)"
  exit 1
fi

compose() {
  docker compose -f "$COMPOSE_FILE" "$@"
}

cleanup() {
  if [[ "${KEEP_VOLUMES}" == "1" ]]; then
    compose down || true
  else
    compose down -v || true
  fi
}

fail() {
  echo ""
  echo "[docker-selftest] FAIL: $*"
  echo ""
  echo "[docker-selftest] docker compose ps:"
  compose ps || true
  echo ""
  echo "[docker-selftest] docker compose logs (tail):"
  compose logs --no-color --tail=200 backend frontend || true
  cleanup
  exit 1
}

json_get() {
  local key="$1"
  if command -v python3 >/dev/null 2>&1; then
    python3 -c "import json,sys; print(json.load(sys.stdin).get('$key',''))"
    return 0
  fi
  if command -v node >/dev/null 2>&1; then
    node -e "const fs=require('fs'); const obj=JSON.parse(fs.readFileSync(0,'utf8')); console.log(obj['$key'] ?? '')"
    return 0
  fi
  echo ""
  return 0
}

wait_for_health() {
  local deadline=$((SECONDS + TIMEOUT_SEC))
  while (( SECONDS < deadline )); do
    if curl -fsS "${UI_BASE}/health" >/dev/null 2>&1; then
      return 0
    fi
    sleep "${POLL_INTERVAL_SEC}"
  done
  return 1
}

echo "[docker-selftest] Starting containers..."
compose up -d --build

trap cleanup EXIT INT TERM

echo "[docker-selftest] Waiting for /health..."
if ! wait_for_health; then
  fail "Timed out waiting for ${UI_BASE}/health"
fi

echo "[docker-selftest] Triggering demo run..."
RUN_ID="$(
  curl -fsS -X POST "${UI_BASE}/api/run" \
    -H "Content-Type: application/json" \
    -d '{"scenario_id":"demo","options":{"resize":320,"every_n_frames":1,"max_frames":60,"seed":12345,"disable_stress":false}}' \
  | json_get "run_id"
)"

if [[ -z "${RUN_ID}" ]]; then
  fail "Could not parse run_id from /api/run response"
fi
echo "[docker-selftest] run_id=${RUN_ID}"

echo "[docker-selftest] Polling run status..."
deadline=$((SECONDS + TIMEOUT_SEC))
while (( SECONDS < deadline )); do
  payload="$(curl -fsS "${UI_BASE}/api/runs/${RUN_ID}")" || fail "GET /api/runs/${RUN_ID} failed"
  status="$(printf '%s' "$payload" | json_get "status")"
  stage="$(printf '%s' "$payload" | json_get "stage")"
  progress="$(printf '%s' "$payload" | json_get "progress")"
  if [[ "$status" == "completed" ]]; then
    echo "[docker-selftest] Completed (stage=${stage}, progress=${progress})"
    exit 0
  fi
  if [[ "$status" == "cancelled" ]]; then
    echo "[docker-selftest] Cancelled (stage=${stage}, progress=${progress})"
    exit 0
  fi
  if [[ "$status" == "failed" ]]; then
    err="$(printf '%s' "$payload" | json_get "error_message")"
    fail "Run failed: ${err}"
  fi
  sleep "${POLL_INTERVAL_SEC}"
done

fail "Timed out waiting for run terminal state (run_id=${RUN_ID})"
