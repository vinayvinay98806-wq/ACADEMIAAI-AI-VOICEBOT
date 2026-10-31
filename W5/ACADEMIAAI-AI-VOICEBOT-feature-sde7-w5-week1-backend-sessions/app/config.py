"""Application configuration module.

Supports environment variables and defaults to safe mock mode
without requiring paid AI provider keys or external credentials.
"""

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings for Team SDE 7 Backend."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Academiaai AI Voicebot Backend"
    team: str = "SDE 7"
    workstream: str = "W5: Backend, Sessions and Observability"
    version: str = "0.1.0"
    environment: str = "development"
    mock_mode: bool = True
    host: str = "127.0.0.1"
    port: int = 8000
    log_level: str = "INFO"
    api_v1_prefix: str = "/api/v1"


@lru_cache()
def get_settings() -> Settings:
    """Return cached application settings instance."""
    return Settings()
