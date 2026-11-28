"""Health and readiness endpoints with aggregated component health monitoring."""

import asyncio
import time
from typing import Any, Dict
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from app.config import Settings, get_settings
from app.gateways.factory import (
    get_audio_gateway,
    get_reasoning_gateway,
    get_transcription_gateway,
    get_workflow_gateway,
)
from app.gateways.protocols import (
    AudioGatewayProtocol,
    ReasoningGatewayProtocol,
    TranscriptionGatewayProtocol,
    WorkflowGatewayProtocol,
)
from app.models.health import HealthResponse, ReadinessResponse
from app.repositories.in_memory_session import (
    InMemorySessionRepository,
    get_session_repository,
)

router = APIRouter(tags=["Health & Readiness"])


class AggregatedHealthResponse(BaseModel):
    """Detailed component health aggregation report."""

    status: str = Field(..., description="Overall health status: ready, degraded, or not_ready")
    timestamp: str = Field(..., description="UTC ISO timestamp of the health inspection")
    service: str = Field(..., description="Service identifier")
    summary: Dict[str, Any] = Field(default_factory=dict, description="Summary counters and health metrics")
    components: Dict[str, Dict[str, Any]] = Field(..., description="Individual component diagnostics")


async def _probe_component(name: str, coro, timeout_seconds: float = 1.5) -> Dict[str, Any]:
    """Execute a component health probe with timeout protection."""
    start = time.perf_counter()
    try:
        res = await asyncio.wait_for(coro, timeout=timeout_seconds)
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        res["latency_ms"] = latency_ms
        res.setdefault("adapter_type", "mock")
        return res
    except asyncio.TimeoutError:
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        return {
            "status": "degraded",
            "error": f"{name} probe timed out after {timeout_seconds}s",
            "latency_ms": latency_ms,
            "adapter_type": "mock",
        }
    except Exception as exc:
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        return {
            "status": "unavailable",
            "error": str(exc),
            "latency_ms": latency_ms,
            "adapter_type": "unknown",
        }


@router.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Service Liveness Check",
    description="Returns lightweight process health status, runtime mode, and version.",
)
async def health_check(
    settings: Settings = Depends(get_settings),
) -> HealthResponse:
    """Lightweight liveness probe ensuring process is alive."""
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
    summary="Service Readiness Probe with Component Aggregation",
    description="Aggregates component readiness across all module gateways and repository.",
)
async def readiness_check(
    settings: Settings = Depends(get_settings),
    repository: InMemorySessionRepository = Depends(get_session_repository),
    audio_gw: AudioGatewayProtocol = Depends(get_audio_gateway),
    transcription_gw: TranscriptionGatewayProtocol = Depends(get_transcription_gateway),
    reasoning_gw: ReasoningGatewayProtocol = Depends(get_reasoning_gateway),
    workflow_gw: WorkflowGatewayProtocol = Depends(get_workflow_gateway),
) -> ReadinessResponse:
    """Readiness probe aggregating internal repository and module gateway statuses."""
    repo_status = "ready" if repository is not None else "unavailable"

    # Query gateway components with timeout safety
    audio_res = await _probe_component("audio_gateway", audio_gw.check_health())
    trans_res = await _probe_component("transcription_gateway", transcription_gw.check_health())
    rsn_res = await _probe_component("reasoning_gateway", reasoning_gw.check_health())
    wf_res = await _probe_component("workflow_gateway", workflow_gw.check_health())

    # Map to dependencies dict
    dependencies = {
        "session_repository": repo_status,
        "mock_provider": "ready" if settings.mock_mode else "disabled",
        "audio_gateway": audio_res.get("status", "unavailable"),
        "transcription_gateway": trans_res.get("status", "unavailable"),
        "reasoning_gateway": rsn_res.get("status", "unavailable"),
        "workflow_gateway": wf_res.get("status", "unavailable"),
        "event_stream": "ready" if repo_status == "ready" else "unavailable",
    }

    # Evaluate overall status
    if repo_status != "ready":
        overall_status = "not_ready"
    elif any(s in ("degraded", "unavailable") for s in [
        dependencies["audio_gateway"],
        dependencies["transcription_gateway"],
        dependencies["reasoning_gateway"],
        dependencies["workflow_gateway"],
    ]):
        overall_status = "degraded"
    else:
        overall_status = "ready"

    return ReadinessResponse(
        status=overall_status,
        service=settings.app_name,
        dependencies=dependencies,
    )


@router.get(
    "/health/aggregated",
    response_model=AggregatedHealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Detailed Aggregated Component Health",
    description="Returns detailed diagnostics for all internal subsystems and gateway adapters.",
)
async def aggregated_health(
    settings: Settings = Depends(get_settings),
    repository: InMemorySessionRepository = Depends(get_session_repository),
    audio_gw: AudioGatewayProtocol = Depends(get_audio_gateway),
    transcription_gw: TranscriptionGatewayProtocol = Depends(get_transcription_gateway),
    reasoning_gw: ReasoningGatewayProtocol = Depends(get_reasoning_gateway),
    workflow_gw: WorkflowGatewayProtocol = Depends(get_workflow_gateway),
) -> AggregatedHealthResponse:
    """Detailed health probe returning rich diagnostic structures for every subsystem."""
    from datetime import datetime, timezone

    audio_res = await _probe_component("audio_gateway", audio_gw.check_health())
    trans_res = await _probe_component("transcription_gateway", transcription_gw.check_health())
    rsn_res = await _probe_component("reasoning_gateway", reasoning_gw.check_health())
    wf_res = await _probe_component("workflow_gateway", workflow_gw.check_health())

    components = {
        "w5_backend": {"status": "ready", "version": settings.version, "mode": "mock" if settings.mock_mode else "prod", "latency_ms": 0.0, "adapter_type": "internal"},
        "session_repository": {"status": "ready" if repository is not None else "unavailable", "latency_ms": 0.0, "adapter_type": "in_memory"},
        "SessionRepository": {"status": "ready" if repository is not None else "unavailable", "latency_ms": 0.0, "adapter_type": "in_memory"},
        "audio_gateway": audio_res,
        "W1_Audio": audio_res,
        "transcription_gateway": trans_res,
        "W2_STT": trans_res,
        "reasoning_gateway": rsn_res,
        "W3_ContextReasoning": rsn_res,
        "workflow_gateway": wf_res,
        "W4_Workflow": wf_res,
        "event_stream": {"status": "ready", "latency_ms": 0.0, "adapter_type": "internal"},
    }

    if any(c.get("status") in ("degraded", "unavailable") for c in components.values()):
        overall = "degraded" if components["session_repository"]["status"] == "ready" else "not_ready"
    else:
        overall = "ready"

    summary = {
        "overall_status": overall,
        "total_components": len(components),
        "healthy_count": sum(1 for c in components.values() if c.get("status") in ("ready", "healthy")),
        "degraded_count": sum(1 for c in components.values() if c.get("status") in ("degraded", "unavailable")),
    }

    return AggregatedHealthResponse(
        status=overall,
        timestamp=datetime.now(timezone.utc).isoformat(),
        service=settings.app_name,
        summary=summary,
        components=components,
    )
