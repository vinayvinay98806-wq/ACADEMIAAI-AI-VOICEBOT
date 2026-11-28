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

    # Week 3 Module Gateway Configuration
    audio_adapter_type: str = Field(
        default="mock",
        description="Audio gateway adapter type ('mock', 'w1', 'auto')",
    )
    transcription_adapter_type: str = Field(
        default="mock",
        description="Transcription gateway adapter type ('mock', 'w2', 'auto')",
    )
    reasoning_adapter_type: str = Field(
        default="mock",
        description="Reasoning gateway adapter type ('mock', 'w3', 'auto')",
    )
    workflow_adapter_type: str = Field(
        default="mock",
        description="Workflow gateway adapter type ('mock', 'w4', 'auto')",
    )
    gateway_timeout_seconds: float = Field(
        default=10.0,
        gt=0,
        description="Default timeout in seconds for cross-module gateway operations",
    )

    # Week 3 Authorization Configuration
    auth_enabled: bool = Field(
        default=False,
        description="Whether authorization is enforced on protected endpoints",
    )
    auth_token: Optional[str] = Field(
        default=None,
        description="Preshared token/API key for local authorization",
    )

    # Week 3 Rate Limiting Configuration
    rate_limit_enabled: bool = Field(
        default=True,
        description="Whether client request rate limiting is enforced",
    )
    rate_limit_requests: int = Field(
        default=100,
        gt=0,
        description="Maximum requests allowed within the rate limit window",
    )
    rate_limit_window_seconds: int = Field(
        default=60,
        gt=0,
        description="Sliding rate limit window in seconds",
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

        if self.gateway_timeout_seconds <= 0:
            raise ConfigurationError(
                f"Invalid gateway timeout: {self.gateway_timeout_seconds}. Timeout must be greater than 0."
            )

        if self.auth_enabled and not self.auth_token:
            raise ConfigurationError(
                "Authentication is enabled (auth_enabled=True) but 'auth_token' is not configured."
            )

        if self.rate_limit_requests <= 0:
            raise ConfigurationError(
                f"Invalid rate limit requests: {self.rate_limit_requests}. Requests must be greater than 0."
            )

        if self.rate_limit_window_seconds <= 0:
            raise ConfigurationError(
                f"Invalid rate limit window: {self.rate_limit_window_seconds}. Window must be greater than 0."
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
        sensitive_keys = {"ai_service_api_key", "database_url", "auth_token"}
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
