# ARES Lite — Counter-UAS Reliability & Engagement Simulator

"Not a drone detector - a battlefield reliability test range that stress-tests detection systems under frontline conditions and outputs an operational readiness score + report."

## Phase 1 Scope

This repository currently provides the Phase 1 scaffold:
- FastAPI backend skeleton
- React + Vite + Tailwind frontend scaffold
- SQLite-ready model stubs
- `make dev` to run backend and frontend together
- `make demo` for a canned scenario readiness output
- Docker Compose dev skeleton

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
│       └── scenarios.json
├── frontend
├── scripts
│   ├── dev.sh
│   └── demo.sh
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

## Available API Stubs (Phase 1)

- `GET /health`
  - Response: `{ "status": "ok", "service": "ares-lite-backend" }`
- `GET /api/scenarios`
  - Response: `{ "scenarios": [{ "id": "...", "name": "...", "description": "..." }] }`

## Docker Compose (Scaffold)

```bash
docker compose -f /Users/yusaf/ARES-lite/docker/docker-compose.yml up
```

This is a development scaffold for backend/frontend services only.

## Notes

- CPU-only by design.
- Offline-first architecture target.
- Later phases will wire ingestion, detection, stress simulation, reliability metrics, engagement simulation, readiness scoring, blind spot explorer, and report generation.
