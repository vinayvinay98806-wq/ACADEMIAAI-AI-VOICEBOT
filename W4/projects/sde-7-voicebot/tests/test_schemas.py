"""
Unit tests for the five core workflow schemas:
1. WorkflowPlan
2. WorkflowStep
3. ToolSpec
4. ApprovalRequest
5. WorkflowResult
"""

import sys
from pathlib import Path

# Add project root to sys.path for direct or discovered execution
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import unittest
from agentic_workflow.schemas import (
    ApprovalRequest,
    ToolSpec,
    WorkflowPlan,
    WorkflowResult,
    WorkflowStep,
)


class TestWorkflowSchemas(unittest.TestCase):
    """Test suite verifying contract creation, helper methods, and serialization."""

    def test_workflow_result_ok(self):
        """Test WorkflowResult ok factory and properties."""
        res = WorkflowResult.ok(output={"data": 123}, metadata={"source": "test"})
        self.assertTrue(res.success)
        self.assertEqual(res.output, {"data": 123})
        self.assertIsNone(res.error)
        self.assertEqual(res.metadata["source"], "test")

        # Roundtrip serialization
        res_dict = res.to_dict()
        reconstructed = WorkflowResult.from_dict(res_dict)
        self.assertEqual(res, reconstructed)

    def test_workflow_result_fail(self):
        """Test WorkflowResult fail factory and properties."""
        res = WorkflowResult.fail(error="Network timed out", metadata={"retries": 3})
        self.assertFalse(res.success)
        self.assertIsNone(res.output)
        self.assertEqual(res.error, "Network timed out")
        self.assertEqual(res.metadata["retries"], 3)

        # Roundtrip serialization
        res_dict = res.to_dict()
        reconstructed = WorkflowResult.from_dict(res_dict)
        self.assertEqual(res, reconstructed)

    def test_tool_spec(self):
        """Test ToolSpec creation and serialization."""
        spec = ToolSpec(
            name="mock_tool",
            description="A test tool",
            parameters_schema={"param1": {"type": "str", "required": True}},
            is_consequential=True,
        )
        self.assertEqual(spec.name, "mock_tool")
        self.assertTrue(spec.is_consequential)
        self.assertIn("param1", spec.parameters_schema)

        # Roundtrip serialization
        spec_dict = spec.to_dict()
        reconstructed = ToolSpec.from_dict(spec_dict)
        self.assertEqual(spec, reconstructed)

    def test_approval_request_lifecycle(self):
        """Test ApprovalRequest creation, approval, and rejection."""
        req = ApprovalRequest(
            request_id="req-1",
            workflow_id="wf-100",
            step_id="step-1",
            tool_name="sensitive_action",
            action_description="Change grade",
        )
        self.assertEqual(req.status, "PENDING")
        self.assertTrue(req.is_pending())
        self.assertFalse(req.is_approved())
        self.assertFalse(req.is_rejected())

        # Test approve
        req.approve(reason="Approved by dean")
        self.assertEqual(req.status, "APPROVED")
        self.assertTrue(req.is_approved())
        self.assertFalse(req.is_pending())
        self.assertEqual(req.decision_reason, "Approved by dean")
        self.assertIsNotNone(req.decided_at)

        # Cannot approve twice
        with self.assertRaises(ValueError):
            req.approve()

        # Test reject on fresh request
        req2 = ApprovalRequest(
            request_id="req-2",
            workflow_id="wf-100",
            step_id="step-2",
            tool_name="sensitive_action",
            action_description="Drop student",
        )
        req2.reject(reason="Disallowed during finals")
        self.assertEqual(req2.status, "REJECTED")
        self.assertTrue(req2.is_rejected())
        self.assertFalse(req2.is_pending())
        self.assertEqual(req2.decision_reason, "Disallowed during finals")

        # Roundtrip serialization
        req_dict = req.to_dict()
        reconstructed = ApprovalRequest.from_dict(req_dict)
        self.assertEqual(req.request_id, reconstructed.request_id)
        self.assertEqual(req.status, reconstructed.status)
        self.assertEqual(req.decision_reason, reconstructed.decision_reason)

    def test_workflow_step(self):
        """Test WorkflowStep creation, result attachment, and serialization."""
        step = WorkflowStep(
            step_id="step_lookup",
            tool_name="academic_lookup",
            input_payload={"record_type": "student", "record_id": "S101"},
            dependencies=[],
            is_consequential=False,
            status="pending",
        )
        self.assertEqual(step.step_id, "step_lookup")
        self.assertEqual(step.tool_name, "academic_lookup")
        self.assertIsNone(step.result)

        step.result = WorkflowResult.ok(output={"name": "Alice"})
        step.status = "completed"

        # Roundtrip serialization
        step_dict = step.to_dict()
        reconstructed = WorkflowStep.from_dict(step_dict)
        self.assertEqual(step.step_id, reconstructed.step_id)
        self.assertEqual(step.status, reconstructed.status)
        self.assertIsNotNone(reconstructed.result)
        self.assertEqual(reconstructed.result.output, {"name": "Alice"})

    def test_workflow_plan(self):
        """Test WorkflowPlan composition, step retrieval, and serialization."""
        step1 = WorkflowStep(step_id="s1", tool_name="tool_a", input_payload={"k": "v"})
        step2 = WorkflowStep(step_id="s2", tool_name="tool_b", dependencies=["s1"])

        plan = WorkflowPlan(
            workflow_id="wf-abc",
            goal="Test plan execution",
            steps=[step1, step2],
            state="draft",
            metadata={"priority": "high"},
        )
        self.assertEqual(plan.workflow_id, "wf-abc")
        self.assertEqual(len(plan.steps), 2)
        self.assertEqual(plan.state, "draft")

        # Lookup step
        found = plan.get_step("s2")
        self.assertIsNotNone(found)
        self.assertEqual(found.step_id, "s2")
        self.assertIsNone(plan.get_step("non_existent"))

        # Add step
        step3 = WorkflowStep(step_id="s3", tool_name="tool_c", dependencies=["s2"])
        plan.add_step(step3)
        self.assertEqual(len(plan.steps), 3)

        # Roundtrip serialization
        plan_dict = plan.to_dict()
        reconstructed = WorkflowPlan.from_dict(plan_dict)
        self.assertEqual(plan.workflow_id, reconstructed.workflow_id)
        self.assertEqual(len(reconstructed.steps), 3)
        self.assertEqual(reconstructed.metadata["priority"], "high")


if __name__ == "__main__":
    unittest.main()
