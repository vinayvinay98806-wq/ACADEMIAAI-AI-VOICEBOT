"""
Agentic Workflow Package - Worker 4 Foundation (Week 1).

Public exports for schemas, state machine, mock tools, validator, and executor.
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
    # Executor
    "WorkflowExecutor",
]
