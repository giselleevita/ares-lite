from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "ARES Lite Backend"
    env: str = "dev"
    database_url: str = "sqlite:///./ares_lite.db"
    data_dir: Path = Path(__file__).resolve().parent.parent / "data"
    runs_dir: Path = data_dir / "runs"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
