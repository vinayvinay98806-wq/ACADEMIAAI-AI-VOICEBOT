"""One-command launcher for the Academiaai Voicebot Backend in Mock Mode.

Team: SDE 7
Workstream: W5 - Backend, Sessions and Observability (Week 1)

Usage:
    python run_mock.py
"""

import os
import sys

# Force mock mode and development environment
os.environ["MOCK_MODE"] = "True"
os.environ["ENVIRONMENT"] = "development"

import uvicorn
from app.config import get_settings


def main() -> None:
    """Launch the FastAPI server in mock mode."""
    settings = get_settings()

    banner = f"""
========================================================================
  ACADEMIAAI AI VOICEBOT BACKEND - TEAM SDE 7
  Workstream: W5 - Backend, Sessions and Observability
  Scope:      Week 2 Implementation (Session Lifecycle, SSE Streaming & Observability)
  Status:     MOCK MODE ACTIVE (No external API keys required)
========================================================================
  Base URL:      http://{settings.host}:{settings.port}
  Health Check:  http://{settings.host}:{settings.port}/health
  Readiness:     http://{settings.host}:{settings.port}/ready
  Standard Sess: POST http://{settings.host}:{settings.port}/api/v1/sessions
  Mock Session:  POST http://{settings.host}:{settings.port}/api/v1/sessions/mock
  Event Stream:  GET  http://{settings.host}:{settings.port}/api/v1/sessions/{'{session_id}'}/events/stream
  Swagger Docs:  http://{settings.host}:{settings.port}/docs
========================================================================
"""
    print(banner)

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
