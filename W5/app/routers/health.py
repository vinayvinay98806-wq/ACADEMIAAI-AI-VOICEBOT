"""Health and readiness endpoints for service monitoring."""

from fastapi import APIRouter, Depends, status

from app.config import Settings, get_settings
from app.models.health import HealthResponse, ReadinessResponse
from app.repositories.in_memory_session import (
    InMemorySessionRepository,
    get_session_repository,
)

router = APIRouter(tags=["Health & Readiness"])


@router.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Service Liveness/Health Check",
    description="Returns service health status, runtime mode, and version.",
)
async def health_check(
    settings: Settings = Depends(get_settings),
) -> HealthResponse:
    """Lightweight health check endpoint."""
    return HealthResponse(
        status="healthy",
        service=settings.app_name,
        version=settings.version,
        mode="mock" if settings.mock_mode else "production",
    )


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    status_code=status.HTTP_200_OK,
    summary="Service Readiness Check",
    description="Reports whether internal dependencies and repositories are ready to serve requests.",
)
async def readiness_check(
    settings: Settings = Depends(get_settings),
    repository: InMemorySessionRepository = Depends(get_session_repository),
) -> ReadinessResponse:
    """Readiness probe verifying local in-memory dependencies."""
    repo_status = "ready" if repository is not None else "unavailable"
    return ReadinessResponse(
        status="ready" if repo_status == "ready" else "not_ready",
        service=settings.app_name,
        dependencies={
            "session_repository": repo_status,
            "mock_provider": "ready" if settings.mock_mode else "disabled",
        },
    )
