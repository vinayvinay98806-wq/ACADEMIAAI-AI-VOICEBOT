"""Gateway coordinator executing cross-module pipelines and recording session events."""

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from fastapi import Depends

from app.config import Settings, get_settings
from app.core.exceptions import GatewayError, GatewayTimeoutError
from app.core.logging import correlation_id_ctx, logger, request_id_ctx, session_id_ctx
from app.gateways.factory import (
    get_audio_gateway,
    get_reasoning_gateway,
    get_transcription_gateway,
    get_workflow_gateway,
)
from app.gateways.protocols import (
    AudioChunkData,
    AudioGatewayProtocol,
    ReasoningGatewayProtocol,
    ReasoningResultData,
    TranscriptionGatewayProtocol,
    TranscriptResult,
    WorkflowGatewayProtocol,
    WorkflowResultData,
)
from app.models.session import SessionEvent
from app.repositories.base import BaseSessionRepository
from app.repositories.in_memory_session import (
    InMemorySessionRepository,
    get_session_repository,
)


@dataclass
class GatewayPipelineResult:
    """Summary of the full cross-workstream interaction pipeline execution."""

    session_id: str
    request_id: str
    correlation_id: str
    audio_chunk: Optional[AudioChunkData] = None
    transcript: Optional[TranscriptResult] = None
    reasoning: Optional[ReasoningResultData] = None
    workflow: Optional[WorkflowResultData] = None
    events_emitted: List[str] = field(default_factory=list)


class GatewayCoordinator:
    """Coordinates cross-workstream execution across W1 Audio, W2 STT, W3 Reasoning, and W4 Workflow."""

    def __init__(
        self,
        audio_gateway: AudioGatewayProtocol,
        transcription_gateway: TranscriptionGatewayProtocol,
        reasoning_gateway: ReasoningGatewayProtocol,
        workflow_gateway: WorkflowGatewayProtocol,
        repository: BaseSessionRepository,
        settings: Optional[Settings] = None,
    ) -> None:
        self.audio = audio_gateway
        self.transcription = transcription_gateway
        self.reasoning = reasoning_gateway
        self.workflow = workflow_gateway
        self.repository = repository
        self.settings = settings or get_settings()

    async def _emit_event(
        self,
        session_id: str,
        event_type: str,
        payload: Dict[str, Any],
        request_id: str,
        correlation_id: str,
    ) -> SessionEvent:
        """Helper to safely record a gateway lifecycle event with ID propagation."""
        evt_id = f"evt-gw-{uuid.uuid4().hex[:8]}"
        enriched_payload = {
            **payload,
            "request_id": request_id,
            "correlation_id": correlation_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        event = SessionEvent(
            event_id=evt_id,
            session_id=session_id,
            event_type=event_type,
            payload=enriched_payload,
            timestamp=datetime.now(timezone.utc),
        )
        return await self.repository.add_event(session_id, event)

    async def process_interaction(
        self,
        session_id: str,
        user_query: Optional[str] = None,
        audio_chunk: Optional[AudioChunkData] = None,
        workflow_goal: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
    ) -> GatewayPipelineResult:
        """Execute the end-to-end integration sequence:
        Audio -> Transcription -> Context/Reasoning -> Workflow -> Session Events.
        """
        request_id = request_id_ctx.get() or f"req-{uuid.uuid4().hex[:10]}"
        correlation_id = correlation_id_ctx.get() or request_id
        session_id_ctx.set(session_id)

        effective_timeout = timeout_seconds or self.settings.gateway_timeout_seconds
        emitted_event_ids: List[str] = []

        logger.info(
            f"Starting gateway interaction pipeline for session {session_id} "
            f"[req_id={request_id}, corr_id={correlation_id}, timeout={effective_timeout}s]"
        )

        try:
            # -------------------------------------------------------------
            # Stage 1: Audio Input Capture (W1)
            # -------------------------------------------------------------
            processed_audio = audio_chunk
            if processed_audio is None and not user_query:
                try:
                    processed_audio = await asyncio.wait_for(
                        self.audio.capture_chunk(session_id=session_id, sequence_number=1, signal_type="speech"),
                        timeout=effective_timeout,
                    )
                except asyncio.TimeoutError:
                    raise GatewayTimeoutError(module_name="W1_Audio", timeout_seconds=effective_timeout)
                except Exception as exc:
                    raise GatewayError(module_name="W1_Audio", message=str(exc))

            if processed_audio is not None:
                audio_evt = await self._emit_event(
                    session_id=session_id,
                    event_type="gateway.audio_processed",
                    payload=processed_audio.to_dict(),
                    request_id=request_id,
                    correlation_id=correlation_id,
                )
                emitted_event_ids.append(audio_evt.event_id)

            # -------------------------------------------------------------
            # Stage 2: Audio Transcription (W2)
            # -------------------------------------------------------------
            transcript_result: Optional[TranscriptResult] = None
            query_text = user_query

            if not query_text and processed_audio is not None:
                try:
                    transcript_result = await asyncio.wait_for(
                        self.transcription.transcribe(audio_chunk=processed_audio, session_id=session_id),
                        timeout=effective_timeout,
                    )
                    query_text = transcript_result.text
                except asyncio.TimeoutError:
                    raise GatewayTimeoutError(module_name="W2_STT", timeout_seconds=effective_timeout)
                except Exception as exc:
                    raise GatewayError(module_name="W2_STT", message=str(exc))
            elif query_text:
                transcript_result = TranscriptResult(
                    text=query_text,
                    is_final=True,
                    confidence=1.0,
                    metadata={"source": "direct_text_override"},
                )

            if transcript_result is not None:
                trans_evt = await self._emit_event(
                    session_id=session_id,
                    event_type="gateway.transcription_completed",
                    payload=transcript_result.to_dict(),
                    request_id=request_id,
                    correlation_id=correlation_id,
                )
                emitted_event_ids.append(trans_evt.event_id)

            # Fallback if text is still empty
            if not query_text:
                query_text = "What is the course syllabus for CS-101?"

            # -------------------------------------------------------------
            # Stage 3: Context & Reasoning (W3)
            # -------------------------------------------------------------
            try:
                reasoning_result = await asyncio.wait_for(
                    self.reasoning.reason(
                        query=query_text,
                        session_id=session_id,
                        context={"request_id": request_id, "correlation_id": correlation_id},
                    ),
                    timeout=effective_timeout,
                )
            except asyncio.TimeoutError:
                raise GatewayTimeoutError(module_name="W3_Reasoning", timeout_seconds=effective_timeout)
            except Exception as exc:
                raise GatewayError(module_name="W3_Reasoning", message=str(exc))

            rsn_evt = await self._emit_event(
                session_id=session_id,
                event_type="gateway.reasoning_completed",
                payload=reasoning_result.to_dict(),
                request_id=request_id,
                correlation_id=correlation_id,
            )
            emitted_event_ids.append(rsn_evt.event_id)

            # -------------------------------------------------------------
            # Stage 4: Agentic Workflow Execution (W4)
            # -------------------------------------------------------------
            target_goal = workflow_goal or reasoning_result.suggested_action or "academic_lookup"
            try:
                workflow_result = await asyncio.wait_for(
                    self.workflow.execute_plan(goal=target_goal, session_id=session_id),
                    timeout=effective_timeout,
                )
            except asyncio.TimeoutError:
                raise GatewayTimeoutError(module_name="W4_Workflow", timeout_seconds=effective_timeout)
            except Exception as exc:
                raise GatewayError(module_name="W4_Workflow", message=str(exc))

            wf_evt = await self._emit_event(
                session_id=session_id,
                event_type="gateway.workflow_executed",
                payload=workflow_result.to_dict(),
                request_id=request_id,
                correlation_id=correlation_id,
            )
            emitted_event_ids.append(wf_evt.event_id)

            # Final summary event
            summary_evt = await self._emit_event(
                session_id=session_id,
                event_type="gateway.interaction_completed",
                payload={
                    "status": "success",
                    "events_count": len(emitted_event_ids) + 1,
                    "query": query_text,
                    "response": reasoning_result.response_text,
                    "workflow_status": workflow_result.status,
                },
                request_id=request_id,
                correlation_id=correlation_id,
            )
            emitted_event_ids.append(summary_evt.event_id)

            logger.info(
                f"Completed gateway interaction pipeline for session {session_id} "
                f"[events_emitted={len(emitted_event_ids)}]"
            )

            return GatewayPipelineResult(
                session_id=session_id,
                request_id=request_id,
                correlation_id=correlation_id,
                audio_chunk=processed_audio,
                transcript=transcript_result,
                reasoning=reasoning_result,
                workflow=workflow_result,
                events_emitted=emitted_event_ids,
            )

        except Exception as exc:
            # Record failure in session event log for observability
            logger.error(f"Gateway interaction pipeline failed for session {session_id}: {exc}")
            fail_evt = await self._emit_event(
                session_id=session_id,
                event_type="gateway.interaction_failed",
                payload={
                    "status": "failed",
                    "error_type": exc.__class__.__name__,
                    "error_message": str(exc),
                },
                request_id=request_id,
                correlation_id=correlation_id,
            )
            emitted_event_ids.append(fail_evt.event_id)
            raise


def get_gateway_coordinator(
    audio_gateway: AudioGatewayProtocol = Depends(get_audio_gateway),
    transcription_gateway: TranscriptionGatewayProtocol = Depends(get_transcription_gateway),
    reasoning_gateway: ReasoningGatewayProtocol = Depends(get_reasoning_gateway),
    workflow_gateway: WorkflowGatewayProtocol = Depends(get_workflow_gateway),
    repository: InMemorySessionRepository = Depends(get_session_repository),
    settings: Settings = Depends(get_settings),
) -> GatewayCoordinator:
    """Dependency injection provider for GatewayCoordinator."""
    return GatewayCoordinator(
        audio_gateway=audio_gateway,
        transcription_gateway=transcription_gateway,
        reasoning_gateway=reasoning_gateway,
        workflow_gateway=workflow_gateway,
        repository=repository,
        settings=settings,
    )
