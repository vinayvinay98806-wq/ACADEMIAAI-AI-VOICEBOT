"""
Unit tests for WorkflowExecutor end-to-end execution, lifecycle, and error handling:
- Multi-step workflow execution
- Dependency resolution
- Pausing and resuming workflow execution
- Cancelling workflow execution
- Step failure propagation
"""

import sys
from pathlib import Path

# Add project root to sys.path for direct or discovered execution
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import unittest
from agentic_workflow.executor import WorkflowExecutor
from agentic_workflow.mock_tools import create_default_registry
from agentic_workflow.schemas import WorkflowPlan, WorkflowStep
from agentic_workflow.state_machine import WorkflowState


class TestWorkflowExecutor(unittest.TestCase):
    """Test suite verifying end-to-end executor operations and controls."""

    def setUp(self):
        self.registry = create_default_registry()
        self.registry.reset_counts()

    def test_multi_step_harmless_execution(self):
        """Test executing a multi-step purely harmless workflow."""
        plan = WorkflowPlan(
            workflow_id="wf-multi-harmless",
            goal="Lookup student and lookup enrolled course",
            steps=[
                WorkflowStep(
                    step_id="step_student",
                    tool_name="academic_lookup",
                    input_payload={"record_type": "student", "record_id": "S101"},
                ),
                WorkflowStep(
                    step_id="step_course",
                    tool_name="academic_lookup",
                    input_payload={"record_type": "course", "record_id": "CS101"},
                    dependencies=["step_student"],
                ),
            ],
        )

        executor = WorkflowExecutor(plan=plan, registry=self.registry)
        result = executor.run()

        self.assertTrue(result.success)
        self.assertEqual(executor.current_state, WorkflowState.SUCCEEDED)
        self.assertEqual(self.registry.get_invocation_count("academic_lookup"), 2)

        step1 = plan.get_step("step_student")
        step2 = plan.get_step("step_course")

        self.assertEqual(step1.status, "completed")
        self.assertEqual(step2.status, "completed")
        self.assertEqual(step1.result.output["name"], "Alice Johnson")
        self.assertEqual(step2.result.output["title"], "Introduction to Computer Science")

    def test_workflow_pause_and_resume(self):
        """Test pausing a running workflow and resuming it to completion."""
        plan = WorkflowPlan(
            workflow_id="wf-pause-resume",
            goal="Test pause and resume",
            steps=[
                WorkflowStep(
                    step_id="step_1",
                    tool_name="academic_lookup",
                    input_payload={"record_type": "student", "record_id": "S101"},
                ),
                WorkflowStep(
                    step_id="step_2",
                    tool_name="academic_lookup",
                    input_payload={"record_type": "student", "record_id": "S102"},
                    dependencies=["step_1"],
                ),
            ],
        )

        executor = WorkflowExecutor(plan=plan, registry=self.registry)

        # Start execution: complete step 1 then pause
        # We can transition to running, then pause
        executor.state_machine.transition_to(WorkflowState.RUNNING)
        new_state = executor.pause(reason="Maintenance break")
        self.assertEqual(new_state, WorkflowState.PAUSED)
        self.assertEqual(executor.current_state, WorkflowState.PAUSED)

        # Resume execution
        resume_result = executor.resume()
        self.assertTrue(resume_result.success)
        self.assertEqual(executor.current_state, WorkflowState.SUCCEEDED)
        self.assertEqual(self.registry.get_invocation_count("academic_lookup"), 2)

    def test_workflow_cancel(self):
        """Test cancelling a workflow prevents further step execution."""
        plan = WorkflowPlan(
            workflow_id="wf-cancel-test",
            goal="Test cancel",
            steps=[
                WorkflowStep(
                    step_id="step_1",
                    tool_name="academic_lookup",
                    input_payload={"record_type": "student", "record_id": "S101"},
                )
            ],
        )

        executor = WorkflowExecutor(plan=plan, registry=self.registry)
        cancel_state = executor.cancel(reason="User abort")

        self.assertEqual(cancel_state, WorkflowState.CANCELLED)
        self.assertEqual(executor.current_state, WorkflowState.CANCELLED)
        self.assertEqual(plan.state, "cancelled")

    def test_step_failure_propagates_to_workflow_failure(self):
        """Test that a tool returning failure halts execution and marks workflow failed."""
        plan = WorkflowPlan(
            workflow_id="wf-failure-test",
            goal="Lookup invalid student",
            steps=[
                WorkflowStep(
                    step_id="step_fail",
                    tool_name="academic_lookup",
                    input_payload={"record_type": "student", "record_id": "S9999_NONEXISTENT"},
                ),
                WorkflowStep(
                    step_id="step_unreached",
                    tool_name="academic_lookup",
                    input_payload={"record_type": "course", "record_id": "CS101"},
                    dependencies=["step_fail"],
                ),
            ],
        )

        executor = WorkflowExecutor(plan=plan, registry=self.registry)
        result = executor.run()

        self.assertFalse(result.success)
        self.assertEqual(executor.current_state, WorkflowState.FAILED)
        self.assertEqual(plan.state, "failed")

        step_fail = plan.get_step("step_fail")
        step_unreached = plan.get_step("step_unreached")

        self.assertEqual(step_fail.status, "failed")
        self.assertEqual(step_unreached.status, "pending")
        # Step 2 was never executed
        self.assertEqual(self.registry.get_invocation_count("academic_lookup"), 1)


if __name__ == "__main__":
    unittest.main()
