"""Application configuration module.

Supports environment variables and defaults to safe mock mode
without requiring paid AI provider keys or external credentials.
"""

from functools import lru_cache
from typing import Any, Dict, Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.exceptions import ConfigurationError


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
    port: int = Field(default=8000, ge=1, le=65535)
    log_level: str = "INFO"
    log_format: str = "text"  # "text" or "json"
    api_v1_prefix: str = "/api/v1"

    # Week 2 Session Lifecycle & Payload Limits
    session_ttl_seconds: int = Field(
        default=1800,
        gt=0,
        description="Session idle expiry TTL in seconds (default 30 minutes)",
    )
    max_payload_size_bytes: int = Field(
        default=1_048_576,
        gt=0,
        description="Maximum allowed request payload size in bytes (default 1MB)",
    )

    # Production Credentials (Optional in mock mode; mandatory in production)
    ai_service_api_key: Optional[str] = Field(
        default=None,
        description="External AI API key (required in production mode)",
    )
    database_url: Optional[str] = Field(
        default=None,
        description="Persistent database connection string (required in production mode)",
    )

    def validate_startup_configuration(self) -> None:
        """Validate startup configuration rules safely.

        - In Mock Mode: Validates that local safe defaults are used with zero external credentials.
        - In Production Mode: Enforces presence of required production credentials and connection strings.
        """
        if self.port < 1 or self.port > 65535:
            raise ConfigurationError(
                f"Invalid port configuration: {self.port}. Port must be between 1 and 65535."
            )

        if self.session_ttl_seconds <= 0:
            raise ConfigurationError(
                f"Invalid session TTL: {self.session_ttl_seconds}. TTL must be greater than 0."
            )

        if self.max_payload_size_bytes <= 0:
            raise ConfigurationError(
                f"Invalid max payload size: {self.max_payload_size_bytes}. Size must be greater than 0."
            )

        # In production mode, required secrets and dependencies must be configured
        if not self.mock_mode:
            missing = []
            placeholders = {"placeholder", "changeme", "your-api-key", "your_key_here", "test"}

            if not self.ai_service_api_key or self.ai_service_api_key.strip().lower() in placeholders:
                missing.append("ai_service_api_key")

            if not self.database_url or self.database_url.strip().lower() in placeholders:
                missing.append("database_url")

            if missing:
                raise ConfigurationError(
                    f"Production startup failed: missing or invalid production settings: {', '.join(missing)}. "
                    "Ensure valid production credentials are provided via environment variables.",
                    details={"missing_fields": missing},
                )

    def safe_dict(self) -> Dict[str, Any]:
        """Return configuration dictionary with sensitive secrets masked."""
        data = self.model_dump()
        sensitive_keys = {"ai_service_api_key", "database_url"}
        for key in sensitive_keys:
            if data.get(key):
                val = str(data[key])
                if len(val) > 8:
                    data[key] = f"{val[:3]}...{val[-3:]}"
                else:
                    data[key] = "***"
        return data


@lru_cache()
def get_settings() -> Settings:
    """Return cached application settings instance."""
    return Settings()
