"""
Unit tests for PlanValidator:
- Structural validation (empty IDs, goal, step array)
- Duplicate step ID rejection
- Unregistered tool verification
- Parameter conformance to ToolSpec schema
- Dependency reference validation & self-dependency detection
- DAG cycle detection (direct and indirect circular dependencies)
"""

import sys
from pathlib import Path

# Add project root to sys.path for direct or discovered execution
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import unittest
from agentic_workflow.mock_tools import create_default_registry
from agentic_workflow.schemas import WorkflowPlan, WorkflowStep
from agentic_workflow.validator import PlanValidationError, PlanValidator


class TestPlanValidator(unittest.TestCase):
    """Test suite verifying strict static validation of workflow plans."""

    def setUp(self):
        self.registry = create_default_registry()
        self.validator = PlanValidator(self.registry)

    def test_valid_plan_passes(self):
        """Verify that a well-formed plan passes validation without error."""
        plan = WorkflowPlan(
            workflow_id="wf-valid-1",
            goal="Lookup student and update status",
            steps=[
                WorkflowStep(
                    step_id="step-1",
                    tool_name="academic_lookup",
                    input_payload={"record_type": "student", "record_id": "S101"},
                ),
                WorkflowStep(
                    step_id="step-2",
                    tool_name="student_status_update",
                    input_payload={
                        "student_id": "S101",
                        "new_status": "active",
                        "reason": "Continuing enrollment",
                    },
                    dependencies=["step-1"],
                ),
            ],
        )
        # Should not raise
        self.validator.validate(plan)

    def test_missing_workflow_id(self):
        """Verify plan fails if workflow_id is empty."""
        plan = WorkflowPlan(
            workflow_id="",
            goal="Test",
            steps=[WorkflowStep(step_id="s1", tool_name="academic_lookup", input_payload={"record_type": "student", "record_id": "S101"})],
        )
        with self.assertRaises(PlanValidationError) as ctx:
            self.validator.validate(plan)
        self.assertIn("non-empty 'workflow_id'", str(ctx.exception))

    def test_missing_goal(self):
        """Verify plan fails if goal is empty."""
        plan = WorkflowPlan(
            workflow_id="wf-1",
            goal="   ",
            steps=[WorkflowStep(step_id="s1", tool_name="academic_lookup", input_payload={"record_type": "student", "record_id": "S101"})],
        )
        with self.assertRaises(PlanValidationError) as ctx:
            self.validator.validate(plan)
        self.assertIn("non-empty 'goal'", str(ctx.exception))

    def test_empty_steps(self):
        """Verify plan fails if steps list is empty."""
        plan = WorkflowPlan(workflow_id="wf-1", goal="Valid goal", steps=[])
        with self.assertRaises(PlanValidationError) as ctx:
            self.validator.validate(plan)
        self.assertIn("contain at least one step", str(ctx.exception))

    def test_duplicate_step_id(self):
        """Verify plan fails if duplicate step IDs are detected."""
        plan = WorkflowPlan(
            workflow_id="wf-dup",
            goal="Test duplicates",
            steps=[
                WorkflowStep(step_id="step-same", tool_name="academic_lookup", input_payload={"record_type": "student", "record_id": "S101"}),
                WorkflowStep(step_id="step-same", tool_name="academic_lookup", input_payload={"record_type": "course", "record_id": "CS101"}),
            ],
        )
        with self.assertRaises(PlanValidationError) as ctx:
            self.validator.validate(plan)
        self.assertIn("Duplicate step_id detected", str(ctx.exception))

    def test_unregistered_tool(self):
        """Verify plan fails if an unknown tool is specified."""
        plan = WorkflowPlan(
            workflow_id="wf-bad-tool",
            goal="Use nonexistent tool",
            steps=[
                WorkflowStep(step_id="s1", tool_name="arbitrary_unregistered_tool", input_payload={}),
            ],
        )
        with self.assertRaises(PlanValidationError) as ctx:
            self.validator.validate(plan)
        self.assertIn("specifies unregistered tool", str(ctx.exception))

    def test_missing_required_parameter(self):
        """Verify plan fails if a required parameter is missing from the payload."""
        plan = WorkflowPlan(
            workflow_id="wf-missing-param",
            goal="Missing record_id",
            steps=[
                WorkflowStep(step_id="s1", tool_name="academic_lookup", input_payload={"record_type": "student"}),
            ],
        )
        with self.assertRaises(PlanValidationError) as ctx:
            self.validator.validate(plan)
        self.assertIn("missing required parameter 'record_id'", str(ctx.exception))

    def test_invalid_parameter_type(self):
        """Verify plan fails if a parameter has an incorrect data type."""
        plan = WorkflowPlan(
            workflow_id="wf-bad-type",
            goal="Bad type",
            steps=[
                WorkflowStep(step_id="s1", tool_name="academic_lookup", input_payload={"record_type": 12345, "record_id": "S101"}),
            ],
        )
        with self.assertRaises(PlanValidationError) as ctx:
            self.validator.validate(plan)
        self.assertIn("must be a str", str(ctx.exception))

    def test_disallowed_parameter_value(self):
        """Verify plan fails if a parameter has a value outside allowed_values."""
        plan = WorkflowPlan(
            workflow_id="wf-bad-value",
            goal="Bad enum value",
            steps=[
                WorkflowStep(step_id="s1", tool_name="academic_lookup", input_payload={"record_type": "invalid_type", "record_id": "S101"}),
            ],
        )
        with self.assertRaises(PlanValidationError) as ctx:
            self.validator.validate(plan)
        self.assertIn("not in allowed values", str(ctx.exception))

    def test_unknown_dependency(self):
        """Verify plan fails if a dependency references a nonexistent step."""
        plan = WorkflowPlan(
            workflow_id="wf-missing-dep",
            goal="Missing dep",
            steps=[
                WorkflowStep(step_id="s1", tool_name="academic_lookup", input_payload={"record_type": "student", "record_id": "S101"}, dependencies=["ghost_step"]),
            ],
        )
        with self.assertRaises(PlanValidationError) as ctx:
            self.validator.validate(plan)
        self.assertIn("unknown dependency 'ghost_step'", str(ctx.exception))

    def test_self_dependency(self):
        """Verify plan fails if a step depends on itself."""
        plan = WorkflowPlan(
            workflow_id="wf-self-dep",
            goal="Self dep",
            steps=[
                WorkflowStep(step_id="s1", tool_name="academic_lookup", input_payload={"record_type": "student", "record_id": "S101"}, dependencies=["s1"]),
            ],
        )
        with self.assertRaises(PlanValidationError) as ctx:
            self.validator.validate(plan)
        self.assertIn("cannot depend on itself", str(ctx.exception))

    def test_circular_dependency_two_steps(self):
        """Verify detection of a 2-step cycle (A depends on B, B depends on A)."""
        plan = WorkflowPlan(
            workflow_id="wf-cycle-2",
            goal="Direct circular dependency",
            steps=[
                WorkflowStep(step_id="step_a", tool_name="academic_lookup", input_payload={"record_type": "student", "record_id": "S101"}, dependencies=["step_b"]),
                WorkflowStep(step_id="step_b", tool_name="academic_lookup", input_payload={"record_type": "course", "record_id": "CS101"}, dependencies=["step_a"]),
            ],
        )
        with self.assertRaises(PlanValidationError) as ctx:
            self.validator.validate(plan)
        self.assertIn("Circular dependency detected", str(ctx.exception))

    def test_circular_dependency_three_steps(self):
        """Verify detection of a 3-step cycle (A depends on B, B depends on C, C depends on A)."""
        plan = WorkflowPlan(
            workflow_id="wf-cycle-3",
            goal="Indirect circular dependency",
            steps=[
                WorkflowStep(step_id="step_1", tool_name="academic_lookup", input_payload={"record_type": "student", "record_id": "S101"}, dependencies=["step_3"]),
                WorkflowStep(step_id="step_2", tool_name="academic_lookup", input_payload={"record_type": "student", "record_id": "S102"}, dependencies=["step_1"]),
                WorkflowStep(step_id="step_3", tool_name="academic_lookup", input_payload={"record_type": "course", "record_id": "CS101"}, dependencies=["step_2"]),
            ],
        )
        with self.assertRaises(PlanValidationError) as ctx:
            self.validator.validate(plan)
        self.assertIn("Circular dependency detected", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
