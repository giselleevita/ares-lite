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

## Run Development Stack

```bash
cd /Users/yusaf/ARES-lite
make dev
```

Expected output includes lines similar to:
- `Uvicorn running on http://127.0.0.1:8000`
- `Local:   http://127.0.0.1:5173/`

## Run Canned Demo

```bash
cd /Users/yusaf/ARES-lite
make demo
```

Expected output:
- `urban_dusk readiness: 82`
- `forest_occlusion readiness: 67`
- `degradation observed under stress: yes`

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

Expected response (example):

```json
{
  "run_id": "run_ab12cd34ef56",
  "scenario_id": "urban_dusk",
  "status": "completed",
  "processed_at": "2026-02-12T12:00:00+00:00",
  "frames_processed": 60,
  "detections_written": 60,
  "detector_backend": "motion",
  "inference_seconds": 0.08,
  "fallback_reason": "ultralytics unavailable: No module named 'ultralytics'"
}
```

3. Verify run record:

```bash
curl http://127.0.0.1:8000/api/runs/<run_id>
```

Expected:
- status `completed`
- config matches `resize`, `every_n_frames`, `max_frames`
- extracted frame images under `backend/data/runs/<run_id>/frames`
- SQLite rows in `runs` and `detections`

## Available API Endpoints

- `GET /health`
  - Response: `{ "status": "ok", "service": "ares-lite-backend" }`
- `GET /api/scenarios`
  - Response: `{ "scenarios": [{ "id": "...", "name": "...", "description": "...", "clip": "...", "ground_truth": "..." }] }`
- `POST /api/run`
  - Input:
    - `scenario_id: string`
    - `options: { resize: int, every_n_frames: int, max_frames: int }`
  - Behavior: synchronous short run, writes run + detections to SQLite
  - Detector selection:
    - tries YOLO (`ultralytics` + `yolov8n.pt`)
    - auto-falls back to motion detector on load failure/inference failure/timeout
- `GET /api/runs/{run_id}`
  - Response: run status/config snapshot from SQLite

## Docker Compose (Scaffold)

```bash
docker compose -f /Users/yusaf/ARES-lite/docker/docker-compose.yml up
```

This is a development scaffold for backend/frontend services only.

## Notes

- CPU-only by design.
- Offline-first architecture target.
- If `ffmpeg` is missing, `/api/run` returns a clear error.
- If `ultralytics` is missing, runs continue via motion fallback.
- Later phases will wire stress simulation, reliability metrics, engagement simulation, readiness scoring, blind spot explorer, and report generation.
