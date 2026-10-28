"""
Unit tests for the two harmless deterministic mock tools and ToolRegistry:
1. academic_lookup (non-consequential read-only query tool)
2. student_status_update (consequential state modification tool)
"""

import sys
from pathlib import Path

# Add project root to sys.path for direct or discovered execution
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import unittest
from agentic_workflow.mock_tools import (
    ACADEMIC_LOOKUP_SPEC,
    STUDENT_STATUS_UPDATE_SPEC,
    ToolRegistry,
    academic_lookup_handler,
    create_default_registry,
    student_status_update_handler,
)
from agentic_workflow.schemas import ToolSpec, WorkflowResult


class TestMockTools(unittest.TestCase):
    """Test suite verifying tool contracts, determinism, and registry guarantees."""

    def test_exactly_two_default_tools_exist(self):
        """Verify that create_default_registry contains exactly two registered tools."""
        registry = create_default_registry()
        specs = registry.list_specs()
        self.assertEqual(len(specs), 2)

        tool_names = {s.name for s in specs}
        self.assertEqual(tool_names, {"academic_lookup", "student_status_update"})

    def test_academic_lookup_consequentiality(self):
        """Verify academic_lookup is non-consequential and read-only."""
        self.assertFalse(ACADEMIC_LOOKUP_SPEC.is_consequential)
        self.assertEqual(ACADEMIC_LOOKUP_SPEC.name, "academic_lookup")

    def test_student_status_update_consequentiality(self):
        """Verify student_status_update is consequential."""
        self.assertTrue(STUDENT_STATUS_UPDATE_SPEC.is_consequential)
        self.assertEqual(STUDENT_STATUS_UPDATE_SPEC.name, "student_status_update")

    def test_academic_lookup_student_success(self):
        """Test looking up valid student records deterministically."""
        res = academic_lookup_handler({"record_type": "student", "record_id": "S101"})
        self.assertTrue(res.success)
        self.assertIsNotNone(res.output)
        self.assertEqual(res.output["student_id"], "S101")
        self.assertEqual(res.output["name"], "Alice Johnson")
        self.assertEqual(res.output["major"], "Computer Science")

    def test_academic_lookup_student_not_found(self):
        """Test looking up nonexistent student record."""
        res = academic_lookup_handler({"record_type": "student", "record_id": "S999"})
        self.assertFalse(res.success)
        self.assertIn("Student record 'S999' not found", res.error)

    def test_academic_lookup_course_success(self):
        """Test looking up valid course records deterministically."""
        res = academic_lookup_handler({"record_type": "course", "record_id": "CS101"})
        self.assertTrue(res.success)
        self.assertIsNotNone(res.output)
        self.assertEqual(res.output["course_id"], "CS101")
        self.assertEqual(res.output["title"], "Introduction to Computer Science")

    def test_academic_lookup_course_not_found(self):
        """Test looking up nonexistent course record."""
        res = academic_lookup_handler({"record_type": "course", "record_id": "CS999"})
        self.assertFalse(res.success)
        self.assertIn("Course record 'CS999' not found", res.error)

    def test_academic_lookup_invalid_type(self):
        """Test looking up unsupported record type."""
        res = academic_lookup_handler({"record_type": "faculty", "record_id": "F01"})
        self.assertFalse(res.success)
        self.assertIn("Invalid record_type", res.error)

    def test_student_status_update_success(self):
        """Test updating student status deterministically in mock store."""
        res = student_status_update_handler({
            "student_id": "S102",
            "new_status": "on_leave",
            "reason": "Medical leave of absence",
        })
        self.assertTrue(res.success)
        self.assertEqual(res.output["student_id"], "S102")
        self.assertEqual(res.output["new_status"], "on_leave")
        self.assertEqual(res.output["reason"], "Medical leave of absence")

        # Verify lookup reflects updated status
        lookup_res = academic_lookup_handler({"record_type": "student", "record_id": "S102"})
        self.assertTrue(lookup_res.success)
        self.assertEqual(lookup_res.output["status"], "on_leave")

    def test_student_status_update_invalid_status(self):
        """Test updating student status with an illegal status value."""
        res = student_status_update_handler({
            "student_id": "S101",
            "new_status": "expelled_invalid",
            "reason": "Policy breach",
        })
        self.assertFalse(res.success)
        self.assertIn("Invalid status", res.error)

    def test_student_status_update_nonexistent_student(self):
        """Test updating status of nonexistent student."""
        res = student_status_update_handler({
            "student_id": "S999",
            "new_status": "graduated",
            "reason": "Finished requirements",
        })
        self.assertFalse(res.success)
        self.assertIn("Student 'S999' does not exist", res.error)

    def test_registry_registration_and_duplicate_prevention(self):
        """Test ToolRegistry rejects duplicate tool registrations."""
        registry = ToolRegistry()
        registry.register(ACADEMIC_LOOKUP_SPEC, academic_lookup_handler)
        self.assertTrue(registry.has_tool("academic_lookup"))

        with self.assertRaises(ValueError):
            registry.register(ACADEMIC_LOOKUP_SPEC, academic_lookup_handler)

    def test_registry_invocation_count_and_unregistered_tool(self):
        """Test invocation counter tracking and unregistered tool rejection."""
        registry = create_default_registry()
        self.assertEqual(registry.get_invocation_count("academic_lookup"), 0)

        # Execute once
        res = registry.execute("academic_lookup", {"record_type": "student", "record_id": "S101"})
        self.assertTrue(res.success)
        self.assertEqual(registry.get_invocation_count("academic_lookup"), 1)

        # Reset counts
        registry.reset_counts()
        self.assertEqual(registry.get_invocation_count("academic_lookup"), 0)

        # Execute unregistered tool
        res_unregistered = registry.execute("unregistered_tool", {})
        self.assertFalse(res_unregistered.success)
        self.assertIn("not registered", res_unregistered.error)


if __name__ == "__main__":
    unittest.main()
