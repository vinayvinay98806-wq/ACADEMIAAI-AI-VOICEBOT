"""
Agentic Workflow Package - Worker 4 (Weeks 1–3).

Public exports for schemas, state machine, mock tools, validator, approval manager,
checkpoint & recovery, idempotency, audit trail & progress events, external adapters,
and executor.
"""

from .schemas import (
    ApprovalRequest,
    ToolSpec,
    WorkflowPlan,
    WorkflowResult,
    WorkflowStep,
)
from .state_machine import (
    IllegalStateTransitionError,
    StateTransitionRecord,
    VALID_TRANSITIONS,
    WorkflowState,
    WorkflowStateMachine,
)
from .mock_tools import (
    ACADEMIC_LOOKUP_SPEC,
    STUDENT_STATUS_UPDATE_SPEC,
    ToolRegistry,
    academic_lookup_handler,
    create_default_registry,
    student_status_update_handler,
)
from .validator import (
    PlanValidationError,
    PlanValidator,
)
from .approval_manager import (
    ApprovalAuditEntry,
    ApprovalError,
    ApprovalManager,
)
from .checkpoint import (
    CheckpointError,
    CheckpointNotFoundError,
    CheckpointStore,
    FileCheckpointStore,
    InMemoryCheckpointStore,
    InvalidCheckpointError,
    RecoveryError,
    WorkflowCheckpoint,
    evaluate_step_recoverability,
    validate_checkpoint,
)
from .idempotency import (
    DuplicateExecutionError,
    IdempotencyError,
    IdempotencyRecord,
    IdempotencyStore,
)
from .audit import (
    AuditTrailManager,
    ExecutionHistory,
    ProgressEventType,
    StepAuditRecord,
    WorkflowProgressEvent,
)
from .integrations import (
    ApprovalUIService,
    BackendApprovalClient,
    BackendApprovalState,
    BackendUnavailableError,
    HttpBackendApprovalClient,
    MockBackendApprovalClient,
    ProposalValidationError,
    UIApprovalAction,
    UIApprovalResponse,
    UIApprovalView,
    WorkflowProposalAdapter,
)
from .executor import (
    WorkflowExecutor,
)

__all__ = [
    # Schemas (5 core contracts defined exactly once)
    "WorkflowPlan",
    "WorkflowStep",
    "ToolSpec",
    "ApprovalRequest",
    "WorkflowResult",
    # State Machine
    "WorkflowState",
    "WorkflowStateMachine",
    "IllegalStateTransitionError",
    "VALID_TRANSITIONS",
    "StateTransitionRecord",
    # Tools and Registry
    "ToolRegistry",
    "create_default_registry",
    "ACADEMIC_LOOKUP_SPEC",
    "STUDENT_STATUS_UPDATE_SPEC",
    "academic_lookup_handler",
    "student_status_update_handler",
    # Validator
    "PlanValidator",
    "PlanValidationError",
    # Approval Manager
    "ApprovalManager",
    "ApprovalError",
    "ApprovalAuditEntry",
    # Checkpoint & Recovery (Week 3)
    "WorkflowCheckpoint",
    "CheckpointStore",
    "InMemoryCheckpointStore",
    "FileCheckpointStore",
    "CheckpointError",
    "CheckpointNotFoundError",
    "InvalidCheckpointError",
    "RecoveryError",
    "validate_checkpoint",
    "evaluate_step_recoverability",
    # Idempotency (Week 3)
    "IdempotencyStore",
    "IdempotencyRecord",
    "IdempotencyError",
    "DuplicateExecutionError",
    # Audit Trail & Progress Events (Week 3)
    "AuditTrailManager",
    "StepAuditRecord",
    "WorkflowProgressEvent",
    "ProgressEventType",
    "ExecutionHistory",
    # External Integrations (Week 3)
    "WorkflowProposalAdapter",
    "ProposalValidationError",
    "BackendApprovalClient",
    "MockBackendApprovalClient",
    "HttpBackendApprovalClient",
    "BackendApprovalState",
    "BackendUnavailableError",
    "ApprovalUIService",
    "UIApprovalAction",
    "UIApprovalView",
    "UIApprovalResponse",
    # Executor
    "WorkflowExecutor",
]
