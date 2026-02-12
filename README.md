# ARES Lite — Counter-UAS Reliability & Engagement Simulator

"Not a drone detector - a battlefield reliability test range that stress-tests detection systems under frontline conditions and outputs an operational readiness score + report."

## Current Scope

Implemented so far:
- **Phase 1**: full repo scaffold, backend/frontend boot, dev orchestration, canned demo output.
- **Phase 2**: offline synthetic dataset with ground-truth annotations (2 drone-like clips + 1 clutter clip).

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
│   ├── simulation
│   ├── metrics
│   ├── engagement
│   ├── reporting
│   ├── db
│   │   └── models.py
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
- `ffmpeg` (required to regenerate synthetic clips)
- Optional: Docker Desktop

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

## Available API Stubs (Phase 1)

- `GET /health`
  - Response: `{ "status": "ok", "service": "ares-lite-backend" }`
- `GET /api/scenarios`
  - Response: `{ "scenarios": [{ "id": "...", "name": "...", "description": "...", "clip": "...", "ground_truth": "..." }] }`

## Docker Compose (Scaffold)

```bash
docker compose -f /Users/yusaf/ARES-lite/docker/docker-compose.yml up
```

This is a development scaffold for backend/frontend services only.

## Notes

- CPU-only by design.
- Offline-first architecture target.
- Later phases will wire ingestion, detection, stress simulation, reliability metrics, engagement simulation, readiness scoring, blind spot explorer, and report generation.
