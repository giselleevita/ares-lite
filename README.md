# ARES Lite — Counter-UAS Reliability & Engagement Simulator

"Not a drone detector - a battlefield reliability test range that stress-tests detection systems under frontline conditions and outputs an operational readiness score + report."

## Current Scope

Implemented so far:
- **Phase 1**: full repo scaffold, backend/frontend boot, dev orchestration, canned demo output.
- **Phase 2**: offline synthetic dataset with ground-truth annotations (2 drone-like clips + 1 clutter clip).
- **Phase 3**: ingestion + frame pipeline with synchronous `/api/run` execution and SQLite persistence.
- **Phase 4**: detector interface with YOLOv8n path and automatic motion-based fallback.

## Repository Layout

```text
/Users/yusaf/ARES-lite
├── backend
│   ├── main.py
│   ├── demo.py
│   ├── requirements.txt
│   ├── core
│   │   ├── settings.py
│   │   ├── logging.py
│   │   └── ids.py
│   ├── pipeline
│   │   ├── ingest.py
│   │   ├── frames.py
│   │   ├── inference.py
│   │   └── run.py
│   ├── simulation
│   ├── metrics
│   ├── engagement
│   ├── reporting
│   ├── db
│   │   ├── models.py
│   │   └── session.py
│   └── data
│       ├── scenarios.json
│       ├── dataset_manifest.json
│       ├── clips/
│       └── annotations/
├── frontend
├── scripts
│   ├── dev.sh
│   ├── demo.sh
│   └── generate_synthetic_dataset.py
├── docker
│   └── docker-compose.yml
├── Makefile
├── README.md
└── DEMO.md
```

## Prerequisites

- macOS
- Python 3.10+
- Node.js + npm
- GNU Make
- `ffmpeg` (required for frame extraction and dataset generation)
- Optional: Docker Desktop
- Optional for YOLO mode: `ultralytics` (if absent, motion fallback is automatic)

## Setup

```bash
cd /Users/yusaf/ARES-lite
make setup
```

Expected output includes:
- Python virtualenv created at `backend/.venv`
- Python dependencies installed from `backend/requirements.txt`
- Frontend dependencies installed in `frontend/node_modules`

Optional quick sanity check (requires `ffmpeg`):

```bash
cd /Users/yusaf/ARES-lite
make selfcheck
```

## Run Development Stack

```bash
cd /Users/yusaf/ARES-lite
make dev
```

Expected output includes lines similar to:
- `Uvicorn running on http://127.0.0.1:8000`
- `Local:   http://127.0.0.1:5173/`

## Doctor (Environment Check)

```bash
cd /Users/yusaf/ARES-lite
make doctor
```

This prints a copy/paste friendly checklist for:
- `ffmpeg` / `ffprobe`
- data/runs write permissions
- SQLite path + WAL mode
- warn-only checks (Python version, disk space)

## Run Demo (One Command)

```bash
cd /Users/yusaf/ARES-lite
make demo
```

This will:
1) run `make doctor`
2) generate the built-in golden demo assets if missing
3) start backend + frontend dev servers

Then open `http://127.0.0.1:5173/` and click **Run Demo** (fixed seed, reproducible).

## Docker Demo (Runs Anywhere)

Requirements: Docker Desktop (or Docker Engine) + `docker compose`.

```bash
cd /Users/yusaf/ARES-lite
make docker-demo
```

Then open:
- UI: `http://127.0.0.1:5173/`
- Backend health (proxied): `http://127.0.0.1:5173/health`
- Backend health (direct): `http://127.0.0.1:8000/health`

Notes:
- The built-in golden demo assets are generated on demand inside the backend container and persisted via a named volume.
- The SQLite DB is stored under the `runs` volume (`/app/backend/data/runs/ares_lite.db`).
 - The frontend container proxies `/api/*` to the backend container so the UI can use relative API paths (no build-time localhost coupling).

### Docker Selftest (End-to-End)

This proves the full system works inside Docker: nginx proxy, backend worker, demo assets generation, and run completion.

```bash
cd /Users/yusaf/ARES-lite
make docker-selftest
```

Controls:
- `TIMEOUT_SEC=240 make docker-selftest`
- `KEEP_VOLUMES=1 make docker-selftest` (keeps named volumes for debugging)

### Offline Demo (No Servers)

If you want a quick, synchronous pipeline run without starting the dev stack:

```bash
cd /Users/yusaf/ARES-lite/backend
.venv/bin/python -m demo
```

## Phase 2 Dataset: How to Run + Expected Output

Generate or refresh dataset assets:

```bash
cd /Users/yusaf/ARES-lite
make dataset
```

Expected output includes:
- paths for generated clips:
  - `backend/data/clips/urban_dusk_demo.mp4`
  - `backend/data/clips/forest_occlusion_demo.mp4`
  - `backend/data/clips/clutter_false_positive.mp4`
- confirmation that annotation files were created under `backend/data/annotations`

Sanity checks:
- each clip is 854x480, 15 FPS, 8 seconds
- annotation JSONs have frame keys `0..119`

## Phase 3+4 Run Pipeline: How to Run + Expected Output

1. Start backend:

```bash
cd /Users/yusaf/ARES-lite/backend
.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
```

2. Trigger a run:

```bash
curl -X POST http://127.0.0.1:8000/api/run \
  -H 'Content-Type: application/json' \
  -d '{"scenario_id":"urban_dusk","options":{"resize":640,"every_n_frames":2,"max_frames":120}}'
```

Expected response (example): `POST /api/run` is **asynchronous** and returns immediately with a queued run.

```json
{
  "run_id": "run_ab12cd34ef56",
  "scenario_id": "urban_dusk",
  "status": "queued",
  "processed_at": "2026-02-12T12:00:00+00:00",
  "frames_processed": 0,
  "detections_written": 0,
  "detector_backend": "pending",
  "inference_seconds": 0.0,
  "fallback_reason": null
}
```

3. Poll run status until completion:

```bash
curl http://127.0.0.1:8000/api/runs/<run_id>
```

## Certification Kit (Evidence + Gates + Deltas)

ARES Lite ships an offline-friendly “acceptance kit” for demos and test readiness.

### Evidence Packs (Chain-of-Custody)

- Run evidence pack: `GET /api/runs/{run_id}/evidence.zip`
- Batch evidence pack: `GET /api/benchmarks/{batch_id}/evidence.zip`

Each ZIP includes a `manifest.json` with SHA256 hashes, environment hints (ffmpeg/sqlite), and warnings if any artifacts were missing. Evidence packs are best-effort and never require external services.

### Policy-as-Code Gates (PASS/FAIL)

- Gate config (defaults): `backend/data/gates.json`
- Read active config: `GET /api/gates`
- Update config (local/dev): `POST /api/gates`
- Evaluate run: `GET /api/runs/{run_id}/gate`
- Evaluate batch: `GET /api/benchmarks/{batch_id}/gate`

### Delta-First Compare

- Compare runs with a baseline: `POST /api/compare` with `{ run_ids: [...], baseline_run_id: "run_x" }`
- Response includes per-field `deltas` plus `top_regressions` (worst deltas by directionality).

## Port Overrides (Local + Docker)

If ports `8000` / `5173` are already in use, you can override them:

- Docker: `ARES_BACKEND_PORT=8001 ARES_FRONTEND_PORT=5174 make docker-demo`
- Docker selftest: `ARES_BACKEND_PORT=8001 ARES_FRONTEND_PORT=5174 make docker-selftest`

Expected:
- status transitions `queued -> processing -> completed` (or `failed`)
- progress fields: `stage`, `progress`, `message`
- config matches `resize`, `every_n_frames`, `max_frames`
- extracted frame images under `backend/data/runs/<run_id>/frames`
- SQLite rows in `runs` and `detections`

Optional: synchronous debug endpoint (blocks the request thread):

```bash
curl -X POST http://127.0.0.1:8000/api/run/sync \
  -H 'Content-Type: application/json' \
  -d '{"scenario_id":"urban_dusk","options":{"resize":640,"every_n_frames":2,"max_frames":120}}'
```

## Golden Demo Scenario (Reproducible)

ARES Lite exposes a built-in `demo` scenario that generates its clip + ground truth on demand under `backend/data/demo/`.

Recommended demo run (fixed seed):

```bash
curl -X POST http://127.0.0.1:8000/api/run \
  -H 'Content-Type: application/json' \
  -d '{"scenario_id":"demo","options":{"resize":320,"every_n_frames":1,"max_frames":60,"seed":12345}}'
```

## Available API Endpoints

- `GET /health`
  - Response: `{ "status": "ok", "service": "ares-lite-backend" }`
- `GET /api/scenarios`
  - Response: `{ "scenarios": [{ "id": "...", "name": "...", "description": "...", "clip": "...", "ground_truth": "..." }] }`
- `POST /api/run`
  - Input:
    - `scenario_id: string`
    - `options: { resize: int, every_n_frames: int, max_frames: int }`
  - Behavior: **asynchronous** run; returns immediately with `run_id` and enqueues work
  - Detector selection:
    - tries YOLO (`ultralytics` + `yolov8n.pt`)
    - auto-falls back to motion detector on load failure/inference failure/timeout
- `GET /api/runs/{run_id}`
  - Response: run status + progress (`stage`, `progress`, `message`) + config snapshot from SQLite
- `POST /api/runs/{run_id}/cancel`
  - Behavior:
    - if `queued`: cancels immediately (`status=cancelled`)
    - if `processing`: sets `cancel_requested=true`; run stops at safe checkpoints
    - idempotent for terminal runs (`completed/failed/cancelled`)

## Docker Compose (Scaffold)

```bash
docker compose -f /Users/yusaf/ARES-lite/docker/docker-compose.yml up
```

This is a development scaffold for backend/frontend services only.

## Notes

- CPU-only by design.
- Offline-first architecture target.
- If `ffmpeg` is missing, runs will fail with a clear `error_message` visible via `GET /api/runs/{run_id}`.
- If `ultralytics` is missing, runs continue via motion fallback.
- Runs are queued in SQLite (the `runs` table) and a local background worker thread claims and executes queued runs.
- Later phases will wire stress simulation, reliability metrics, engagement simulation, readiness scoring, blind spot explorer, and report generation.
