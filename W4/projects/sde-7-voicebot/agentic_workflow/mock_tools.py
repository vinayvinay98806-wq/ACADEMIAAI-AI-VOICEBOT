"""
Mock Tools for W4 Agentic Workflow.

Implements exactly two harmless, deterministic mock tools:
1. academic_lookup (non-consequential read-only query tool)
2. student_status_update (consequential action tool requiring explicit approval)

Includes an allow-listed ToolRegistry managing specifications, input schema
validation, and invocation tracking.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple
from .schemas import ToolSpec, WorkflowResult


# In-memory deterministic mock database for student and course records
MOCK_STUDENTS: Dict[str, Dict[str, Any]] = {
    "S101": {
        "student_id": "S101",
        "name": "Alice Johnson",
        "major": "Computer Science",
        "status": "active",
        "gpa": 3.85,
        "enrolled_courses": ["CS101", "AI202"],
    },
    "S102": {
        "student_id": "S102",
        "name": "Bob Smith",
        "major": "Electrical Engineering",
        "status": "active",
        "gpa": 3.40,
        "enrolled_courses": ["ENG301"],
    },
    "S103": {
        "student_id": "S103",
        "name": "Carol Davis",
        "major": "Data Science",
        "status": "on_leave",
        "gpa": 3.92,
        "enrolled_courses": [],
    },
}

MOCK_COURSES: Dict[str, Dict[str, Any]] = {
    "CS101": {
        "course_id": "CS101",
        "title": "Introduction to Computer Science",
        "department": "Computer Science",
        "credits": 4,
        "instructor": "Dr. Alan Turing",
    },
    "AI202": {
        "course_id": "AI202",
        "title": "Artificial Intelligence Foundations",
        "department": "Computer Science",
        "credits": 3,
        "instructor": "Dr. Marvin Minsky",
    },
    "ENG301": {
        "course_id": "ENG301",
        "title": "Signals and Systems",
        "department": "Electrical Engineering",
        "credits": 4,
        "instructor": "Dr. Claude Shannon",
    },
}

# Allowed values for student_status_update
ALLOWED_STATUSES = {"active", "on_leave", "probation", "graduated"}


# ---------------------------------------------------------------------------
# Tool 1: academic_lookup (Harmless, Read-Only, Non-Consequential)
# ---------------------------------------------------------------------------

ACADEMIC_LOOKUP_SPEC = ToolSpec(
    name="academic_lookup",
    description="Deterministically look up student profile or course catalog information",
    is_consequential=False,
    parameters_schema={
        "record_type": {
            "type": "str",
            "required": True,
            "allowed_values": ["student", "course"],
            "description": "Type of record to look up ('student' or 'course')",
        },
        "record_id": {
            "type": "str",
            "required": True,
            "description": "Identifier for the student (e.g. 'S101') or course (e.g. 'CS101')",
        },
    },
)


def academic_lookup_handler(payload: Dict[str, Any]) -> WorkflowResult:
    """
    Deterministic mock handler for looking up academic records.
    Read-only, completely isolated, returns deterministic in-memory data.
    """
    record_type = payload.get("record_type")
    record_id = payload.get("record_id")

    if record_type == "student":
        student = MOCK_STUDENTS.get(str(record_id))
        if student is None:
            return WorkflowResult.fail(
                error=f"Student record '{record_id}' not found.",
                metadata={"record_type": "student", "record_id": record_id},
            )
        return WorkflowResult.ok(
            output=dict(student),
            metadata={"record_type": "student", "record_id": record_id},
        )

    elif record_type == "course":
        course = MOCK_COURSES.get(str(record_id))
        if course is None:
            return WorkflowResult.fail(
                error=f"Course record '{record_id}' not found.",
                metadata={"record_type": "course", "record_id": record_id},
            )
        return WorkflowResult.ok(
            output=dict(course),
            metadata={"record_type": "course", "record_id": record_id},
        )

    else:
        return WorkflowResult.fail(
            error=f"Invalid record_type '{record_type}'. Allowed values: ['student', 'course'].",
            metadata={"record_type": record_type},
        )


# ---------------------------------------------------------------------------
# Tool 2: student_status_update (Harmless In-Memory Mock, Consequential)
# ---------------------------------------------------------------------------

STUDENT_STATUS_UPDATE_SPEC = ToolSpec(
    name="student_status_update",
    description="Update student enrollment or academic status (consequential action requiring explicit approval)",
    is_consequential=True,
    parameters_schema={
        "student_id": {
            "type": "str",
            "required": True,
            "description": "Unique identifier of the student (e.g. 'S101')",
        },
        "new_status": {
            "type": "str",
            "required": True,
            "allowed_values": ["active", "on_leave", "probation", "graduated"],
            "description": "Target status for the student",
        },
        "reason": {
            "type": "str",
            "required": True,
            "description": "Reason for the status modification",
        },
    },
)


def student_status_update_handler(payload: Dict[str, Any]) -> WorkflowResult:
    """
    Deterministic mock handler for updating student status.
    Harmless local mock (modifies local in-memory dict, no external writes).
    Classified as consequential, requiring prior explicit approval.
    """
    student_id = str(payload.get("student_id", ""))
    new_status = str(payload.get("new_status", ""))
    reason = str(payload.get("reason", ""))

    if not student_id:
        return WorkflowResult.fail("Parameter 'student_id' is required.")

    if new_status not in ALLOWED_STATUSES:
        return WorkflowResult.fail(
            f"Invalid status '{new_status}'. Allowed values: {sorted(ALLOWED_STATUSES)}."
        )

    student = MOCK_STUDENTS.get(student_id)
    if student is None:
        return WorkflowResult.fail(f"Student '{student_id}' does not exist.")

    previous_status = student.get("status", "unknown")
    # Update local in-memory record deterministically
    student["status"] = new_status

    return WorkflowResult.ok(
        output={
            "student_id": student_id,
            "name": student.get("name"),
            "previous_status": previous_status,
            "new_status": new_status,
            "reason": reason,
        },
        metadata={"consequential": True, "action": "status_update"},
    )


# ---------------------------------------------------------------------------
# Tool Registry
# ---------------------------------------------------------------------------

class ToolRegistry:
    """
    Allow-list tool registry managing tool specifications and execution handlers.
    Guarantees that only registered, allow-listed tools can be executed.
    Tracks invocation counts for validation and audit testing.
    """

    def __init__(self) -> None:
        self._tools: Dict[str, Tuple[ToolSpec, Callable[[Dict[str, Any]], WorkflowResult]]] = {}
        self._invocation_counts: Dict[str, int] = {}

    def register(
        self,
        spec: ToolSpec,
        handler: Callable[[Dict[str, Any]], WorkflowResult],
    ) -> None:
        """Register a tool specification and handler."""
        if spec.name in self._tools:
            raise ValueError(f"Tool '{spec.name}' is already registered.")
        self._tools[spec.name] = (spec, handler)
        self._invocation_counts[spec.name] = 0

    def has_tool(self, name: str) -> bool:
        """Check if a tool is registered."""
        return name in self._tools

    def get_spec(self, name: str) -> ToolSpec:
        """Get the specification for a registered tool."""
        if name not in self._tools:
            raise KeyError(f"Tool '{name}' is not registered.")
        return self._tools[name][0]

    def get_invocation_count(self, name: str) -> int:
        """Return the number of times a tool handler has been invoked."""
        return self._invocation_counts.get(name, 0)

    def reset_counts(self) -> None:
        """Reset invocation counts to 0."""
        for k in self._invocation_counts:
            self._invocation_counts[k] = 0

    def list_specs(self) -> List[ToolSpec]:
        """Return list of all registered tool specifications."""
        return [spec for spec, _ in self._tools.values()]

    def execute(self, name: str, payload: Dict[str, Any]) -> WorkflowResult:
        """
        Execute a registered tool handler with the given payload.
        Increments the tool invocation counter upon actual invocation.
        """
        if name not in self._tools:
            return WorkflowResult.fail(f"Tool '{name}' is not registered in the allow-list.")

        spec, handler = self._tools[name]
        self._invocation_counts[name] = self._invocation_counts.get(name, 0) + 1

        try:
            return handler(payload)
        except Exception as ex:
            return WorkflowResult.fail(
                error=f"Unhandled error executing tool '{name}': {str(ex)}",
                metadata={"exception_type": type(ex).__name__},
            )


def create_default_registry() -> ToolRegistry:
    """
    Factory creating a ToolRegistry pre-populated with exactly the two
    harmless deterministic mock tools:
    1. academic_lookup
    2. student_status_update
    """
    registry = ToolRegistry()
    registry.register(ACADEMIC_LOOKUP_SPEC, academic_lookup_handler)
    registry.register(STUDENT_STATUS_UPDATE_SPEC, student_status_update_handler)
    return registry
