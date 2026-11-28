"""Dynamic module adapters that integrate actual teammate packages when present."""

import asyncio
from typing import Any, Dict, List, Optional

from app.core.logging import logger
from app.gateways.mock_adapters import (
    MockAudioGatewayAdapter,
    MockReasoningGatewayAdapter,
    MockTranscriptionGatewayAdapter,
    MockWorkflowGatewayAdapter,
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


class W1AudioAdapter(AudioGatewayProtocol):
    """Adapter integrating W1 `src.academiaai.audio` when installed."""

    def __init__(self) -> None:
        self._fallback = MockAudioGatewayAdapter()
        self._available = False
        try:
            import academiaai.audio  # noqa: F401
            self._available = True
            logger.info("W1 Audio package successfully detected.")
        except ImportError:
            logger.info("W1 Audio package not installed; using deterministic mock fallback.")

    @property
    def is_available(self) -> bool:
        return self._available

    async def capture_chunk(
        self, session_id: str, sequence_number: int = 0, signal_type: str = "speech"
    ) -> AudioChunkData:
        if not self._available:
            return await self._fallback.capture_chunk(session_id, sequence_number, signal_type)

        try:
            from academiaai.audio import FakeMicrophoneSource, SignalType, ThresholdVAD
            sig = SignalType.SINE if signal_type == "speech" else SignalType.SILENCE
            mic = FakeMicrophoneSource(signal_type=sig, sample_rate_hz=16000)
            chunk = mic.read_chunk()
            vad = ThresholdVAD()
            vad_res = vad.process_chunk(chunk)
            return AudioChunkData(
                data=chunk.data,
                sample_rate_hz=chunk.format.sample_rate_hz,
                channels=chunk.format.channels,
                format_name=chunk.format.format_name,
                duration_ms=chunk.format.duration_ms,
                sequence_number=chunk.sequence_number,
                is_speech=vad_res.is_speech,
                rms_energy=vad_res.rms_energy,
                metadata={"provider": "W1_AudioPipeline"},
            )
        except Exception as exc:
            logger.warning(f"Error invoking W1 Audio module: {exc}; falling back to mock.")
            return await self._fallback.capture_chunk(session_id, sequence_number, signal_type)

    async def check_health(self) -> Dict[str, Any]:
        if not self._available:
            mock_health = await self._fallback.check_health()
            mock_health["note"] = "w1_module_absent_fallback_active"
            return mock_health
        return {"status": "ready", "provider": "W1AudioAdapter", "mode": "native"}


class W2TranscriptionAdapter(TranscriptionGatewayProtocol):
    """Adapter integrating W2 `w2_stt` when installed."""

    def __init__(self) -> None:
        self._fallback = MockTranscriptionGatewayAdapter()
        self._available = False
        try:
            import w2_stt  # noqa: F401
            self._available = True
            logger.info("W2 STT package successfully detected.")
        except ImportError:
            logger.info("W2 STT package not installed; using deterministic mock fallback.")

    @property
    def is_available(self) -> bool:
        return self._available

    async def transcribe(
        self, audio_chunk: AudioChunkData, session_id: str, language: str = "en-US"
    ) -> TranscriptResult:
        if not self._available:
            return await self._fallback.transcribe(audio_chunk, session_id, language)

        try:
            from w2_stt import DeterministicFakeTranscriber
            transcriber = DeterministicFakeTranscriber()
            # Wrap synchronous call in thread pool to prevent blocking event loop
            events = await asyncio.to_thread(transcriber.transcribe_chunk, audio_chunk)
            full_text = " ".join(e.segment.text for e in events if getattr(e, "segment", None))
            return TranscriptResult(
                text=full_text or self._fallback.default_text,
                is_final=True,
                confidence=0.98,
                language=language,
                metadata={"provider": "W2_STT"},
            )
        except Exception as exc:
            logger.warning(f"Error invoking W2 STT module: {exc}; falling back to mock.")
            return await self._fallback.transcribe(audio_chunk, session_id, language)

    async def check_health(self) -> Dict[str, Any]:
        if not self._available:
            mock_health = await self._fallback.check_health()
            mock_health["note"] = "w2_module_absent_fallback_active"
            return mock_health
        return {"status": "ready", "provider": "W2TranscriptionAdapter", "mode": "native"}


class W3ReasoningAdapter(ReasoningGatewayProtocol):
    """Adapter integrating W3 `w3_context_reasoning` when installed."""

    def __init__(self) -> None:
        self._fallback = MockReasoningGatewayAdapter()
        self._available = False
        try:
            import w3_context_reasoning  # noqa: F401
            self._available = True
            logger.info("W3 Reasoning package successfully detected.")
        except ImportError:
            logger.info("W3 Reasoning package not installed; using deterministic mock fallback.")

    @property
    def is_available(self) -> bool:
        return self._available

    async def reason(
        self, query: str, session_id: str, context: Optional[Dict[str, Any]] = None
    ) -> ReasoningResultData:
        if not self._available:
            return await self._fallback.reason(query, session_id, context)

        try:
            from w3_context_reasoning import DeterministicMockReasoningEngine, ReasoningRequest
            engine = DeterministicMockReasoningEngine()
            req = ReasoningRequest(
                request_id=f"req-{session_id}",
                session_id=session_id,
                user_query=query,
            )
            res = await asyncio.to_thread(engine.reason, req)
            return ReasoningResultData(
                result_id=res.result_id,
                query=query,
                intent=res.intent,
                response_text=res.response_text,
                confidence_score=res.confidence_score,
                grounded_sources=res.grounded_sources,
                reasoning_steps=res.reasoning_steps,
                metadata={"provider": "W3_ContextReasoning"},
            )
        except Exception as exc:
            logger.warning(f"Error invoking W3 Reasoning module: {exc}; falling back to mock.")
            return await self._fallback.reason(query, session_id, context)

    async def check_health(self) -> Dict[str, Any]:
        if not self._available:
            mock_health = await self._fallback.check_health()
            mock_health["note"] = "w3_module_absent_fallback_active"
            return mock_health
        return {"status": "ready", "provider": "W3ReasoningAdapter", "mode": "native"}


class W4WorkflowAdapter(WorkflowGatewayProtocol):
    """Adapter integrating W4 `agentic_workflow` when installed."""

    def __init__(self) -> None:
        self._fallback = MockWorkflowGatewayAdapter()
        self._available = False
        try:
            import agentic_workflow  # noqa: F401
            self._available = True
            logger.info("W4 Workflow package successfully detected.")
        except ImportError:
            logger.info("W4 Workflow package not installed; using deterministic mock fallback.")

    @property
    def is_available(self) -> bool:
        return self._available

    async def execute_plan(
        self, goal: str, session_id: str, steps: Optional[List[Dict[str, Any]]] = None
    ) -> WorkflowResultData:
        if not self._available:
            return await self._fallback.execute_plan(goal, session_id, steps)

        try:
            from agentic_workflow import WorkflowExecutor, WorkflowPlan, WorkflowStep
            step = WorkflowStep(step_id="step-1", tool_name="academic_lookup", input_payload={"query": goal})
            plan = WorkflowPlan(workflow_id=f"wf-{session_id}", goal=goal, steps=[step])
            executor = WorkflowExecutor(plan=plan)
            res = await asyncio.to_thread(executor.execute)
            return WorkflowResultData(
                workflow_id=plan.workflow_id,
                goal=goal,
                success=res.success,
                status=plan.state,
                output=res.output or {},
                error=res.error,
                metadata={"provider": "W4_AgenticWorkflow"},
            )
        except Exception as exc:
            logger.warning(f"Error invoking W4 Workflow module: {exc}; falling back to mock.")
            return await self._fallback.execute_plan(goal, session_id, steps)

    async def check_health(self) -> Dict[str, Any]:
        if not self._available:
            mock_health = await self._fallback.check_health()
            mock_health["note"] = "w4_module_absent_fallback_active"
            return mock_health
        return {"status": "ready", "provider": "W4WorkflowAdapter", "mode": "native"}
