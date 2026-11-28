"""Gateway factory providing dependency-injected adapter instances based on configuration."""

from functools import lru_cache
from fastapi import Depends

from app.config import Settings, get_settings
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
    AudioGatewayProtocol,
    ReasoningGatewayProtocol,
    TranscriptionGatewayProtocol,
    WorkflowGatewayProtocol,
)


@lru_cache()
def get_audio_gateway() -> AudioGatewayProtocol:
    """Provide configured Audio gateway adapter."""
    settings = get_settings()
    adapter_type = settings.audio_adapter_type.lower()
    if adapter_type == "w1":
        return W1AudioAdapter()
    elif adapter_type == "auto":
        w1 = W1AudioAdapter()
        return w1 if w1.is_available else MockAudioGatewayAdapter()
    return MockAudioGatewayAdapter()


@lru_cache()
def get_transcription_gateway() -> TranscriptionGatewayProtocol:
    """Provide configured Transcription gateway adapter."""
    settings = get_settings()
    adapter_type = settings.transcription_adapter_type.lower()
    if adapter_type == "w2":
        return W2TranscriptionAdapter()
    elif adapter_type == "auto":
        w2 = W2TranscriptionAdapter()
        return w2 if w2.is_available else MockTranscriptionGatewayAdapter()
    return MockTranscriptionGatewayAdapter()


@lru_cache()
def get_reasoning_gateway() -> ReasoningGatewayProtocol:
    """Provide configured Reasoning gateway adapter."""
    settings = get_settings()
    adapter_type = settings.reasoning_adapter_type.lower()
    if adapter_type == "w3":
        return W3ReasoningAdapter()
    elif adapter_type == "auto":
        w3 = W3ReasoningAdapter()
        return w3 if w3.is_available else MockReasoningGatewayAdapter()
    return MockReasoningGatewayAdapter()


@lru_cache()
def get_workflow_gateway() -> WorkflowGatewayProtocol:
    """Provide configured Workflow gateway adapter."""
    settings = get_settings()
    adapter_type = settings.workflow_adapter_type.lower()
    if adapter_type == "w4":
        return W4WorkflowAdapter()
    elif adapter_type == "auto":
        w4 = W4WorkflowAdapter()
        return w4 if w4.is_available else MockWorkflowGatewayAdapter()
    return MockWorkflowGatewayAdapter()
