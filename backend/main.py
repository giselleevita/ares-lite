import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from core.logging import configure_logging
from core.settings import settings

configure_logging()

app = FastAPI(title="ARES Lite Backend", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "ares-lite-backend"}


@app.get("/api/scenarios")
def get_scenarios() -> dict[str, Any]:
    scenarios_path = Path(settings.data_dir) / "scenarios.json"
    if not scenarios_path.exists():
        raise HTTPException(status_code=500, detail="Scenario config missing")

    with scenarios_path.open("r", encoding="utf-8") as f:
        payload = json.load(f)

    return payload
