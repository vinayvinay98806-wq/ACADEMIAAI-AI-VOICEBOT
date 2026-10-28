"""Health and readiness response models."""

from datetime import datetime, timezone
from typing import Dict
from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Health status response payload."""

    status: str = Field(default="healthy", description="Service health indicator")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp of the check",
    )
    service: str = Field(default="academiaai-voicebot-backend", description="Service identifier")
    version: str = Field(default="0.1.0", description="Application version")
    mode: str = Field(default="mock", description="Runtime execution mode")


class ReadinessResponse(BaseModel):
    """Readiness status response payload."""

    status: str = Field(default="ready", description="Readiness indicator for serving traffic")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp of the check",
    )
    service: str = Field(default="academiaai-voicebot-backend", description="Service identifier")
    dependencies: Dict[str, str] = Field(
        default_factory=lambda: {
            "session_repository": "ready",
            "mock_provider": "ready",
        },
        description="Readiness status of local dependencies",
    )
