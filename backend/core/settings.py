from pathlib import Path

from pydantic import Field
from pydantic.aliases import AliasChoices
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "ARES Lite Backend"
    env: str = "dev"
    database_url: str = "sqlite:///./ares_lite.db"
    data_dir: Path = Field(
        default=Path(__file__).resolve().parent.parent / "data",
        validation_alias=AliasChoices("ARES_DATA_DIR", "DATA_DIR"),
    )
    runs_dir: Path | None = Field(
        default=None,
        validation_alias=AliasChoices("ARES_RUNS_DIR", "RUNS_DIR"),
    )

    # Worker / recovery settings (local/offline defaults).
    worker_enabled: bool = True
    worker_lock_path: Path | None = Field(
        default=None,
        validation_alias=AliasChoices("ARES_WORKER_LOCK_PATH", "WORKER_LOCK_PATH"),
    )
    worker_poll_interval_sec: float = 0.5
    run_recover_stale_processing_seconds: int = 6 * 60 * 60  # 6 hours
    run_recover_mode: str = "requeue"  # or "fail"
    cancel_check_every_n_frames: int = 10

    detector_preference: str = "auto"
    yolo_model_path: str = "yolov8n.pt"
    yolo_conf_threshold: float = 0.25
    detector_time_budget_sec: float = 10.0

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    def model_post_init(self, __context: object) -> None:
        # Derive dependent paths after env overrides are applied.
        if self.runs_dir is None:
            self.runs_dir = Path(self.data_dir) / "runs"
        if self.worker_lock_path is None:
            self.worker_lock_path = Path(self.runs_dir) / ".worker.lock"


settings = Settings()
