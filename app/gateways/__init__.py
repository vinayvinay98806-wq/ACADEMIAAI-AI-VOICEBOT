"""Gateways package providing cross-workstream contracts, mock/module adapters, and coordinator."""

from app.gateways.coordinator import GatewayCoordinator, GatewayPipelineResult, get_gateway_coordinator
from app.gateways.factory import (
    get_audio_gateway,
    get_reasoning_gateway,
    get_transcription_gateway,
    get_workflow_gateway,
)
from app.gateways.mock_adapters import (
    MockAudioGatewayAdapter,
    MockReasoningGatewayAdapter,
    MockTranscriptionGatewayAdapter,
    MockWorkflowGatewayAdapter,
)
from app.gateways.module_adapters import (
    W1AudioAdapter,
    W2TranscriptionAdapter,
    W3ReasoningAdapter,
    W4WorkflowAdapter,
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

__all__ = [
    # Protocols & Data
    "AudioChunkData",
    "TranscriptResult",
    "ReasoningResultData",
    "WorkflowResultData",
    "AudioGatewayProtocol",
    "TranscriptionGatewayProtocol",
    "ReasoningGatewayProtocol",
    "WorkflowGatewayProtocol",
    # Mocks
    "MockAudioGatewayAdapter",
    "MockTranscriptionGatewayAdapter",
    "MockReasoningGatewayAdapter",
    "MockWorkflowGatewayAdapter",
    # Module Adapters
    "W1AudioAdapter",
    "W2TranscriptionAdapter",
    "W3ReasoningAdapter",
    "W4WorkflowAdapter",
    # Factory & Coordinator
    "get_audio_gateway",
    "get_transcription_gateway",
    "get_reasoning_gateway",
    "get_workflow_gateway",
    "GatewayCoordinator",
    "GatewayPipelineResult",
    "get_gateway_coordinator",
]
