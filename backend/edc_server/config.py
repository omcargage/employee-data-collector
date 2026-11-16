"""Configuration settings for the EDC FastAPI backend."""
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application runtime settings loaded from environment or defaults."""
    model_config = SettingsConfigDict(
        env_prefix="EDC_",
        env_file=".env",
        extra="ignore",
    )

    app_name: str = "EDC Ingestion Server"
    app_version: str = "0.1.0"
    debug: bool = False

    # Database settings: defaults to Docker Compose PostgreSQL 16
    database_url: str = "postgresql+psycopg://edc_user:edc_password@localhost:5432/edc_db"
    db_echo: bool = False
    db_pool_size: int = 10
    db_max_overflow: int = 20


settings = Settings()
