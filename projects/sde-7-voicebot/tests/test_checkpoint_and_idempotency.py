"""
Unit and Integration Tests for Week 3 Days 15-16:
- Workflow checkpoint creation & integrity validation
- Resume after failure and interruption (in-memory & file-backed)
- Completed steps never execute twice
- Failed-step recovery with retry limits & permanent-failure handling
- Idempotency key generation, explicit keys, replay, and concurrent duplicate protection
- Invalid or missing checkpoint rejection
"""

from __future__ import annotations

import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import unittest
from agentic_workflow import (
    CheckpointNotFoundError,
    FileCheckpointStore,
    IdempotencyError,
    IdempotencyStore,
    InMemoryCheckpointStore,
    InvalidCheckpointError,
    RecoveryError,
    ToolSpec,
    WorkflowCheckpoint,
    WorkflowExecutor,
    WorkflowPlan,
    WorkflowResult,
    WorkflowState,
    WorkflowStep,
    create_default_registry,
    validate_checkpoint,
)


class TestCheckpointResumeAndIdempotency(unittest.TestCase):
    """Tests covering Days 15-16 checkpoint, recovery, and idempotency guarantees."""

    def setUp(self) -> None:
        self.registry = create_default_registry()
        self.registry.reset_counts()

    def test_normal_checkpoint_creation_and_fields(self) -> None:
        """Verify checkpoint preserves all required metadata, steps, results, and checksum."""
        store = InMemoryCheckpointStore()
        plan = WorkflowPlan(
            workflow_id="wf-chk-normal",
            goal="Verify checkpoint structure",
            steps=[
                WorkflowStep(
                    step_id="step_1",
                    tool_name="academic_lookup",
                    input_payload={"record_type": "student", "record_id": "S101"},
                ),
                WorkflowStep(
                    step_id="step_2",
                    tool_name="academic_lookup",
                    input_payload={"record_type": "course", "record_id": "CS101"},
                    dependencies=["step_1"],
                ),
            ],
        )
        executor = WorkflowExecutor(plan=plan, registry=self.registry, checkpoint_store=store)
        result = executor.run()
        self.assertTrue(result.success)

        chk = executor.get_latest_checkpoint()
        self.assertIsNotNone(chk)
        assert chk is not None
        self.assertEqual(chk.workflow_id, "wf-chk-normal")
        self.assertEqual(chk.execution_id, executor.execution_id)
        self.assertEqual(chk.current_state, WorkflowState.SUCCEEDED.value)
        self.assertEqual(chk.completed_steps, ["step_1", "step_2"])
        self.assertEqual(chk.pending_steps, [])
        self.assertIsNone(chk.failed_step_info)
        self.assertIn("step_1", chk.step_results)
        self.assertIn("step_2", chk.step_results)
        self.assertIn("step_1", chk.retry_info)
        self.assertTrue(chk.timestamp)
        self.assertIn("records", chk.idempotency_info)
        self.assertTrue(chk.verify_checksum())

    def test_resume_after_failure_preserves_completed_steps(self) -> None:
        """
        Verify that when step_2 fails after step_1 succeeds, resuming from checkpoint
        recovers step_2 and completes step_3 WITHOUT re-executing step_1.
        """
        attempts = {"flaky_step": 0}
        step1_calls = 0

        def counting_lookup(payload: Dict[str, Any]) -> WorkflowResult:
            nonlocal step1_calls
            step1_calls += 1
            return WorkflowResult.ok({"student_id": payload.get("id", "S101")})

        def recoverable_tool(payload: Dict[str, Any]) -> WorkflowResult:
            attempts["flaky_step"] += 1
            if attempts["flaky_step"] == 1:
                return WorkflowResult.fail("Transient upstream service unavailable")
            return WorkflowResult.ok({"recovered": True, "attempt": attempts["flaky_step"]})

        registry = create_default_registry()
        registry.register(
            ToolSpec(name="counting_lookup", description="Count calls", is_idempotent=True),
            counting_lookup,
        )
        registry.register(
            ToolSpec(name="recoverable_tool", description="Fails once then succeeds", is_idempotent=False),
            recoverable_tool,
        )

        store = InMemoryCheckpointStore()
        plan = WorkflowPlan(
            workflow_id="wf-resume-failure",
            goal="Recover after step 2 failure",
            steps=[
                WorkflowStep(step_id="step_1", tool_name="counting_lookup", input_payload={"id": "S101"}),
                WorkflowStep(step_id="step_2", tool_name="recoverable_tool", dependencies=["step_1"]),
                WorkflowStep(
                    step_id="step_3",
                    tool_name="academic_lookup",
                    input_payload={"record_type": "course", "record_id": "CS101"},
                    dependencies=["step_2"],
                ),
            ],
        )

        executor = WorkflowExecutor(plan=plan, registry=registry, checkpoint_store=store)
        first_result = executor.run()
        self.assertFalse(first_result.success)
        self.assertEqual(executor.current_state, WorkflowState.FAILED)
        self.assertEqual(step1_calls, 1)
        self.assertEqual(plan.get_step("step_1").status, "completed")
        self.assertEqual(plan.get_step("step_2").status, "failed")
        self.assertEqual(plan.get_step("step_3").status, "pending")

        # Resume from latest checkpoint -> recovers step_2, executes step_3, NEVER re-runs step_1
        resumed_result = executor.resume_from_checkpoint()
        self.assertTrue(resumed_result.success)
        self.assertEqual(executor.current_state, WorkflowState.SUCCEEDED)
        self.assertEqual(step1_calls, 1, "Completed step_1 must NOT execute twice!")
        self.assertEqual(attempts["flaky_step"], 2)
        self.assertEqual(plan.get_step("step_2").status, "completed")
        self.assertEqual(plan.get_step("step_3").status, "completed")
        self.assertEqual(plan.get_step("step_2").metadata["recovery_attempts"], 1)

    def test_failed_step_recovery_respects_limits_and_permanent_failure(self) -> None:
        """
        Verify recovery attempts are recorded, bounded by max_recovery_attempts,
        and permanently failed steps are rejected safely.
        """
        call_count = 0

        def always_failing(payload: Dict[str, Any]) -> WorkflowResult:
            nonlocal call_count
            call_count += 1
            return WorkflowResult.fail("Persistent failure")

        registry = create_default_registry()
        registry.register(
            ToolSpec(name="always_failing", description="Always fails", is_idempotent=True),
            always_failing,
        )

        plan = WorkflowPlan(
            workflow_id="wf-recovery-limit",
            goal="Test recovery limit",
            steps=[
                WorkflowStep(
                    step_id="step_fail",
                    tool_name="always_failing",
                    max_retries=1,
                    metadata={"max_recovery_attempts": 2},
                )
            ],
        )

        executor = WorkflowExecutor(plan=plan, registry=registry)
        res = executor.run()
        self.assertFalse(res.success)
        initial_calls = call_count  # 1 initial + 1 retry = 2

        # Recovery attempt 1 (allowed)
        res1 = executor.recover_failed_step("step_fail")
        self.assertFalse(res1.success)
        self.assertEqual(plan.get_step("step_fail").metadata["recovery_attempts"], 1)

        # Recovery attempt 2 (allowed, reaches max_recovery_attempts=2)
        res2 = executor.recover_failed_step("step_fail")
        self.assertFalse(res2.success)
        self.assertEqual(plan.get_step("step_fail").metadata["recovery_attempts"], 2)
        calls_after_two = call_count
        self.assertGreater(calls_after_two, initial_calls)

        # Recovery attempt 3 (exhausted -> permanently failed, tool MUST NOT run again)
        res3 = executor.recover_failed_step("step_fail")
        self.assertFalse(res3.success)
        self.assertTrue(res3.metadata.get("permanent_failure"))
        self.assertTrue(plan.get_step("step_fail").metadata.get("permanently_failed"))
        self.assertEqual(call_count, calls_after_two)

    def test_explicit_permanent_failure_not_recovered(self) -> None:
        """Verify steps marked permanent_failure in result metadata cannot be recovered."""
        calls = 0

        def perm_fail(payload: Dict[str, Any]) -> WorkflowResult:
            nonlocal calls
            calls += 1
            return WorkflowResult.fail("Hard schema corruption", metadata={"permanent_failure": True})

        registry = create_default_registry()
        registry.register(ToolSpec(name="perm_fail", description="Permanent fail"), perm_fail)

        plan = WorkflowPlan(
            workflow_id="wf-perm-fail",
            goal="Permanent failure handling",
            steps=[WorkflowStep(step_id="s1", tool_name="perm_fail")],
        )
        executor = WorkflowExecutor(plan=plan, registry=registry)
        executor.run()
        self.assertEqual(calls, 1)

        rec_res = executor.recover_failed_step("s1")
        self.assertFalse(rec_res.success)
        self.assertTrue(rec_res.metadata.get("permanent_failure"))
        self.assertEqual(calls, 1)

    def test_duplicate_idempotency_keys_prevent_duplicate_consequential_execution(self) -> None:
        """
        Verify repeated execution with the same idempotency key does NOT re-invoke
        the consequential tool and returns the previously stored result.
        """
        shared_store = IdempotencyStore()
        idem_key = "idem-status-S101-on-leave"

        # Workflow 1 executes consequential update after approval
        plan1 = WorkflowPlan(
            workflow_id="wf-idem-1",
            goal="Update S101 status once",
            steps=[
                WorkflowStep(
                    step_id="step_update",
                    tool_name="student_status_update",
                    input_payload={"student_id": "S101", "new_status": "on_leave", "reason": "Medical"},
                    metadata={"idempotency_key": idem_key},
                )
            ],
        )
        exec1 = WorkflowExecutor(plan=plan1, registry=self.registry, idempotency_store=shared_store)
        exec1.run()
        exec1.submit_approval("step_update", approved=True, reason="Verified")
        res1 = exec1.run()
        self.assertTrue(res1.success)
        self.assertEqual(self.registry.get_invocation_count("student_status_update"), 1)

        # Workflow 2 uses the EXACT same idempotency_key against the shared store
        plan2 = WorkflowPlan(
            workflow_id="wf-idem-2",
            goal="Duplicate request with same idempotency key",
            steps=[
                WorkflowStep(
                    step_id="step_update_dup",
                    tool_name="student_status_update",
                    input_payload={"student_id": "S101", "new_status": "on_leave", "reason": "Medical"},
                    metadata={"idempotency_key": idem_key},
                )
            ],
        )
        exec2 = WorkflowExecutor(plan=plan2, registry=self.registry, idempotency_store=shared_store)
        exec2.run()
        exec2.submit_approval("step_update_dup", approved=True, reason="Verified")
        res2 = exec2.run()
        self.assertTrue(res2.success)

        # Tool invocation count MUST remain 1!
        self.assertEqual(self.registry.get_invocation_count("student_status_update"), 1)
        step2_res = plan2.get_step("step_update_dup").result
        self.assertIsNotNone(step2_res)
        self.assertTrue(step2_res.metadata.get("idempotency_replay"))
        self.assertEqual(step2_res.output["new_status"], "on_leave")

        # Using same key with a DIFFERENT payload must raise IdempotencyError
        with self.assertRaises(IdempotencyError):
            shared_store.execute(
                idempotency_key=idem_key,
                action=lambda: WorkflowResult.ok({}),
                payload={"student_id": "S101", "new_status": "graduated", "reason": "Different"},
            )

    def test_concurrent_duplicate_execution_runs_tool_once(self) -> None:
        """
        Verify concurrent duplicate requests sharing an idempotency key synchronize
        safely so the underlying tool executes strictly once.
        """
        store = IdempotencyStore()
        call_counter = 0
        counter_lock = threading.Lock()

        def slow_consequential_action() -> WorkflowResult:
            nonlocal call_counter
            time.sleep(0.05)
            with counter_lock:
                call_counter += 1
            return WorkflowResult.ok({"updated": True, "seq": call_counter})

        results: list[tuple[WorkflowResult, bool]] = []
        errors: list[BaseException] = []
        barrier = threading.Barrier(6)

        def worker() -> None:
            try:
                barrier.wait(timeout=2.0)
                outcome = store.execute(
                    idempotency_key="idem-concurrent-001",
                    action=slow_consequential_action,
                    workflow_id="wf-conc",
                    step_id="step_1",
                    tool_name="student_status_update",
                    payload={"student_id": "S102", "new_status": "active"},
                )
                results.append(outcome)
            except BaseException as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        self.assertEqual(errors, [])
        self.assertEqual(len(results), 6)
        self.assertEqual(call_counter, 1, "Concurrent duplicate requests must invoke tool only once!")
        self.assertTrue(all(r.success and r.output["updated"] is True for r, _ in results))
        replayed_count = sum(1 for _, is_replay in results if is_replay)
        self.assertEqual(replayed_count, 5)

    def test_invalid_or_missing_checkpoint_rejected(self) -> None:
        """Verify missing, tampered, malformed, or terminal checkpoints are rejected safely."""
        store = InMemoryCheckpointStore()
        plan = WorkflowPlan(
            workflow_id="wf-invalid-chk",
            goal="Test invalid checkpoint",
            steps=[
                WorkflowStep(
                    step_id="s1",
                    tool_name="academic_lookup",
                    input_payload={"record_type": "student", "record_id": "S101"},
                )
            ],
        )
        executor = WorkflowExecutor(plan=plan, registry=self.registry, checkpoint_store=store)

        # Missing checkpoint
        with self.assertRaises(CheckpointNotFoundError):
            executor.resume_from_checkpoint("chk-does-not-exist")

        # Tampered checksum in-memory after valid restoration
        executor.run()
        chk = executor.get_latest_checkpoint()
        assert chk is not None
        tampered = WorkflowCheckpoint.from_dict(chk.to_dict())
        tampered.completed_steps.append("injected_step")
        with self.assertRaises(InvalidCheckpointError):
            validate_checkpoint(tampered)

        # Missing checksum in serialized dict must be rejected (never recomputed)
        no_checksum_dict = chk.to_dict()
        del no_checksum_dict["checksum"]
        with self.assertRaises(InvalidCheckpointError):
            WorkflowCheckpoint.from_dict(no_checksum_dict)

        # Empty checksum in serialized dict must be rejected
        empty_checksum_dict = chk.to_dict()
        empty_checksum_dict["checksum"] = ""
        with self.assertRaises(InvalidCheckpointError):
            WorkflowCheckpoint.from_dict(empty_checksum_dict)

        # Explicit empty checksum on object fails verify_checksum
        explicit_empty = WorkflowCheckpoint(
            checkpoint_id="chk-empty",
            workflow_id="wf-invalid-chk",
            execution_id="exec-1",
            current_state="paused",
            plan_snapshot=chk.plan_snapshot,
            checksum="",
        )
        self.assertFalse(explicit_empty.verify_checksum())

        # Incorrect checksum in serialized dict must be rejected
        wrong_checksum_dict = chk.to_dict()
        wrong_checksum_dict["checksum"] = "0" * 64
        with self.assertRaises(InvalidCheckpointError):
            WorkflowCheckpoint.from_dict(wrong_checksum_dict)

        # Modified payload with original checksum must be rejected
        modified_payload_dict = chk.to_dict()
        modified_payload_dict["completed_steps"] = []
        with self.assertRaises(InvalidCheckpointError):
            WorkflowCheckpoint.from_dict(modified_payload_dict)

        # Step-status mismatch against plan_snapshot (even if checksum recomputed) must be rejected
        mismatched = WorkflowCheckpoint(
            checkpoint_id="chk-mismatch",
            workflow_id="wf-invalid-chk",
            execution_id="exec-1",
            current_state="paused",
            completed_steps=[],
            pending_steps=[],
            plan_snapshot=chk.plan_snapshot,
        )
        with self.assertRaises(InvalidCheckpointError):
            validate_checkpoint(mismatched)

        # Terminal SUCCEEDED checkpoint cannot be resumed
        with self.assertRaises(InvalidCheckpointError):
            validate_checkpoint(chk, allow_terminal=False)

        # Malformed dict missing fields
        with self.assertRaises(InvalidCheckpointError):
            WorkflowCheckpoint.from_dict({"workflow_id": "wf-1"})

    def test_corrupted_file_checkpoint_and_index_rejected(self) -> None:
        """Verify corrupted .checkpoint.json and .index.json files fail safely."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_store = FileCheckpointStore(tmpdir)
            plan = WorkflowPlan(
                workflow_id="wf-file-corrupt",
                goal="Test file store corruption handling",
                steps=[
                    WorkflowStep(
                        step_id="s1",
                        tool_name="academic_lookup",
                        input_payload={"record_type": "student", "record_id": "S101"},
                    )
                ],
            )
            exec1 = WorkflowExecutor(plan=plan, registry=self.registry, checkpoint_store=file_store)
            exec1.run()
            chk = exec1.get_latest_checkpoint()
            assert chk is not None

            # Corrupt checkpoint JSON on disk
            chk_path = file_store._checkpoint_path(chk.checkpoint_id)
            chk_path.write_text("{corrupted json", encoding="utf-8")
            with self.assertRaises(InvalidCheckpointError):
                file_store.get(chk.checkpoint_id)

            # Corrupt index JSON on disk
            idx_path = file_store._index_path("wf-file-corrupt")
            idx_path.write_text("not valid json", encoding="utf-8")
            with self.assertRaises(InvalidCheckpointError):
                file_store.get_latest("wf-file-corrupt")

            # Malformed non-list or empty-string index entries rejected
            idx_path.write_text('{"bad": "type"}', encoding="utf-8")
            with self.assertRaises(InvalidCheckpointError):
                file_store.list_checkpoints("wf-file-corrupt")

            idx_path.write_text('[""]', encoding="utf-8")
            with self.assertRaises(InvalidCheckpointError):
                file_store.get_latest("wf-file-corrupt")

            # Invalid UTF-8 bytes in index and checkpoint files rejected safely
            idx_path.write_bytes(b"\xff\xfe\xfd")
            with self.assertRaises(InvalidCheckpointError):
                file_store.get_latest("wf-file-corrupt")

            chk_path.write_bytes(b"\xff\xfe\xfd")
            with self.assertRaises(InvalidCheckpointError):
                file_store.get(chk.checkpoint_id)

            # No leftover temp files in directory
            leftover_tmps = [p for p in Path(tmpdir).iterdir() if p.name.endswith(".tmp")]
            self.assertEqual(leftover_tmps, [])

    def test_checkpoint_cross_validation_and_config_restoration(self) -> None:
        """
        Verify:
        - Whitespace/non-string checksums and malformed checkpoint fields raise InvalidCheckpointError.
        - plan_snapshot cross-validation rejects invalid step statuses, duplicates, and mismatched failed_step_info.
        - Checkpoint restoration preserves authorized_permissions, auto_checkpoint, and max_recovery_attempts.
        """
        store = InMemoryCheckpointStore()
        plan = WorkflowPlan(
            workflow_id="wf-chk-cfg",
            goal="Verify full config restoration and cross-validation",
            steps=[
                WorkflowStep(
                    step_id="s1",
                    tool_name="academic_lookup",
                    input_payload={"record_type": "student", "record_id": "S101"},
                ),
                WorkflowStep(
                    step_id="s2",
                    tool_name="student_status_update",
                    input_payload={"student_id": "S101", "new_status": "on_leave", "reason": "Test"},
                    dependencies=["s1"],
                ),
            ],
        )
        exec1 = WorkflowExecutor(
            plan=plan,
            registry=self.registry,
            checkpoint_store=store,
            authorized_permissions={"academic:read", "academic:write"},
            workflow_timeout_seconds=15.0,
            default_step_timeout_seconds=3.0,
            auto_checkpoint=False,
            max_recovery_attempts=1,
        )
        exec1.state_machine.transition_to(WorkflowState.RUNNING)
        s1 = plan.get_step("s1")
        assert s1 is not None
        s1.status = "completed"
        s1.result = WorkflowResult.ok({"student_id": "S101"})
        chk = exec1.save_checkpoint("Manual checkpoint")

        # Whitespace & non-string checksums rejected
        for bad_chk in ("   ", 12345, ["abc"]):
            bad_dict = chk.to_dict()
            bad_dict["checksum"] = bad_chk
            with self.assertRaises(InvalidCheckpointError):
                WorkflowCheckpoint.from_dict(bad_dict)

        # Malformed field types raise InvalidCheckpointError (not raw TypeError/ValueError)
        bad_plan_dict = chk.to_dict()
        bad_plan_dict["plan_snapshot"] = "not-a-dict"
        with self.assertRaises(InvalidCheckpointError):
            WorkflowCheckpoint.from_dict(bad_plan_dict)

        bad_steps_dict = chk.to_dict()
        bad_steps_dict["completed_steps"] = "not-a-list"
        with self.assertRaises(InvalidCheckpointError):
            WorkflowCheckpoint.from_dict(bad_steps_dict)

        # Invalid step status in plan_snapshot rejected
        bad_snap = dict(chk.plan_snapshot)
        bad_snap["steps"] = [dict(chk.plan_snapshot["steps"][0], status="bogus_status"), chk.plan_snapshot["steps"][1]]
        with self.assertRaises(InvalidCheckpointError):
            validate_checkpoint(
                WorkflowCheckpoint(
                    checkpoint_id="chk-bad-status",
                    workflow_id="wf-chk-cfg",
                    execution_id="exec-1",
                    current_state="paused",
                    completed_steps=[],
                    pending_steps=["s2"],
                    plan_snapshot=bad_snap,
                )
            )

        # Duplicate completed_steps rejected
        with self.assertRaises(InvalidCheckpointError):
            validate_checkpoint(
                WorkflowCheckpoint(
                    checkpoint_id="chk-dup-comp",
                    workflow_id="wf-chk-cfg",
                    execution_id="exec-1",
                    current_state="paused",
                    completed_steps=["s1", "s1"],
                    pending_steps=["s2"],
                    plan_snapshot=chk.plan_snapshot,
                )
            )

        # failed_step_info pointing to a non-failed step rejected
        with self.assertRaises(InvalidCheckpointError):
            validate_checkpoint(
                WorkflowCheckpoint(
                    checkpoint_id="chk-bad-failed",
                    workflow_id="wf-chk-cfg",
                    execution_id="exec-1",
                    current_state="failed",
                    completed_steps=["s1"],
                    pending_steps=["s2"],
                    failed_step_info={"step_id": "s1"},
                    plan_snapshot=chk.plan_snapshot,
                )
            )

        # Config restoration preserves permissions, timeouts, auto_checkpoint, max_recovery_attempts
        exec2 = WorkflowExecutor.from_checkpoint(
            chk.checkpoint_id,
            checkpoint_store=store,
            registry=self.registry,
        )
        self.assertEqual(exec2.authorized_permissions, {"academic:read", "academic:write"})
        self.assertFalse(exec2.auto_checkpoint)
        self.assertEqual(exec2.max_recovery_attempts, 1)
        self.assertEqual(exec2.workflow_timeout_seconds, 15.0)
        self.assertEqual(exec2.default_step_timeout_seconds, 3.0)

    def test_checkpoint_restores_timeouts_audit_log_and_downstream_references(self) -> None:
        """
        Verify executor timeouts, Week 2 audit_log, downstream $step output references,
        and skipped downstream steps recover cleanly after checkpoint resume.
        """
        attempts = {"s2": 0}

        def flaky_mid(payload: Dict[str, Any]) -> WorkflowResult:
            attempts["s2"] += 1
            if attempts["s2"] == 1:
                return WorkflowResult.fail("Temporary failure at step 2")
            return WorkflowResult.ok({"course_code": "CS101", "verified_student": payload.get("student")})

        registry = create_default_registry()
        registry.register(ToolSpec(name="flaky_mid", description="Mid step"), flaky_mid)

        store = InMemoryCheckpointStore()
        plan = WorkflowPlan(
            workflow_id="wf-downstream-ref",
            goal="Verify downstream output references and skipped recovery",
            steps=[
                WorkflowStep(
                    step_id="s1",
                    tool_name="academic_lookup",
                    input_payload={"record_type": "student", "record_id": "S101"},
                ),
                WorkflowStep(
                    step_id="s2",
                    tool_name="flaky_mid",
                    input_payload={"student": "$s1.student_id"},
                    dependencies=["s1"],
                ),
                WorkflowStep(
                    step_id="s3",
                    tool_name="academic_lookup",
                    input_payload={"record_type": "course", "record_id": "$s2.course_code"},
                    dependencies=["s2"],
                ),
            ],
        )

        exec1 = WorkflowExecutor(
            plan=plan,
            registry=registry,
            checkpoint_store=store,
            workflow_timeout_seconds=10.0,
            default_step_timeout_seconds=2.0,
        )
        res1 = exec1.run()
        self.assertFalse(res1.success)
        # Simulate s3 having been marked skipped after s2 failure
        exec1._skip_dependent_steps("s2")
        self.assertEqual(plan.get_step("s3").status, "skipped")
        chk = exec1.save_checkpoint("Before recovery with skipped s3")

        exec2 = WorkflowExecutor.from_checkpoint(
            chk.checkpoint_id,
            checkpoint_store=store,
            registry=registry,
        )
        self.assertEqual(exec2.workflow_timeout_seconds, 10.0)
        self.assertEqual(exec2.default_step_timeout_seconds, 2.0)
        self.assertTrue(len(exec2.audit_log) > 0)

        res2 = exec2.resume_from_checkpoint(chk.checkpoint_id)
        self.assertTrue(res2.success)
        self.assertEqual(exec2.current_state, WorkflowState.SUCCEEDED)
        self.assertEqual(exec2.plan.get_step("s2").result.output["verified_student"], "S101")
        self.assertEqual(exec2.plan.get_step("s3").status, "completed")
        self.assertEqual(exec2.plan.get_step("s3").result.output["course_id"], "CS101")

    def test_idempotency_payload_none_and_concurrent_edge_cases(self) -> None:
        """
        Test idempotency edge cases:
        - Second call with payload=None must not bypass mismatch validation
        - Concurrent calls with same key and different payload raise IdempotencyError
        - Concurrent leader failure returns failure and allows subsequent retry
        - Concurrent leader exception propagates cleanly and cleans up in-flight state
        - Concurrent waiter timeout raises IdempotencyError
        """
        store = IdempotencyStore(default_wait_timeout_seconds=2.0)

        # 1. Sequential payload=None must fail if original key used non-empty payload
        res, replayed = store.execute(
            "idem-none-check",
            lambda: WorkflowResult.ok({"x": 1}),
            payload={"student_id": "S101"},
        )
        self.assertTrue(res.success)
        self.assertFalse(replayed)
        with self.assertRaises(IdempotencyError):
            store.execute("idem-none-check", lambda: WorkflowResult.ok({}), payload=None)

        # 2. Concurrent same key, different payload -> waiter raises IdempotencyError
        leader_started = threading.Event()
        release_leader = threading.Event()

        def slow_leader() -> WorkflowResult:
            leader_started.set()
            release_leader.wait(timeout=2.0)
            return WorkflowResult.ok({"ok": True})

        t_leader = threading.Thread(
            target=lambda: store.execute("idem-diff-conc", slow_leader, payload={"id": "A"})
        )
        t_leader.start()
        self.assertTrue(leader_started.wait(timeout=2.0))
        try:
            with self.assertRaises(IdempotencyError):
                store.execute("idem-diff-conc", lambda: WorkflowResult.ok({}), payload={"id": "B"})
        finally:
            release_leader.set()
            t_leader.join(timeout=2.0)

        # 3. Leader returns WorkflowResult.fail -> concurrent waiter gets failure, sequential retry succeeds
        fail_calls = 0
        fail_lock = threading.Lock()
        barrier = threading.Barrier(3)

        def fail_once_action() -> WorkflowResult:
            nonlocal fail_calls
            time.sleep(0.03)
            with fail_lock:
                fail_calls += 1
            if fail_calls == 1:
                return WorkflowResult.fail("Transient leader failure")
            return WorkflowResult.ok({"recovered": True})

        conc_outcomes: list[tuple[WorkflowResult, bool]] = []

        def fail_worker() -> None:
            barrier.wait(timeout=2.0)
            conc_outcomes.append(
                store.execute("idem-leader-fail", fail_once_action, payload={"step": "retry"})
            )

        threads = [threading.Thread(target=fail_worker) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=3.0)

        self.assertEqual(fail_calls, 1)
        self.assertTrue(all(not r.success for r, _ in conc_outcomes))
        # Subsequent sequential retry runs and succeeds because failed result wasn't cached
        retry_res, retry_replayed = store.execute(
            "idem-leader-fail", fail_once_action, payload={"step": "retry"}
        )
        self.assertTrue(retry_res.success)
        self.assertFalse(retry_replayed)
        self.assertEqual(fail_calls, 2)

        # 4. Leader raises exception -> waiter receives exception, in-flight cleaned up, retry works
        exc_calls = 0

        def boom_once() -> WorkflowResult:
            nonlocal exc_calls
            exc_calls += 1
            time.sleep(0.03)
            if exc_calls == 1:
                raise RuntimeError("Unexpected crash")
            return WorkflowResult.ok({"after_crash": True})

        exc_barrier = threading.Barrier(2)
        caught: list[BaseException] = []

        def exc_worker() -> None:
            exc_barrier.wait(timeout=2.0)
            try:
                store.execute("idem-leader-exc", boom_once, payload={"k": "v"})
            except BaseException as ex:
                caught.append(ex)

        t1 = threading.Thread(target=exc_worker)
        t2 = threading.Thread(target=exc_worker)
        t1.start()
        t2.start()
        t1.join(timeout=3.0)
        t2.join(timeout=3.0)
        self.assertEqual(len(caught), 2)
        self.assertEqual(exc_calls, 1)

        after_res, _ = store.execute("idem-leader-exc", boom_once, payload={"k": "v"})
        self.assertTrue(after_res.success)
        self.assertEqual(exc_calls, 2)

        # 5. Waiter timeout
        hold_started = threading.Event()
        hold_release = threading.Event()

        def long_leader() -> WorkflowResult:
            hold_started.set()
            hold_release.wait(timeout=2.0)
            return WorkflowResult.ok({"done": True})

        t_hold = threading.Thread(
            target=lambda: store.execute("idem-timeout", long_leader, payload={"t": 1})
        )
        t_hold.start()
        self.assertTrue(hold_started.wait(timeout=2.0))
        try:
            with self.assertRaises(IdempotencyError) as ctx:
                store.execute(
                    "idem-timeout",
                    lambda: WorkflowResult.ok({}),
                    payload={"t": 1},
                    wait_timeout_seconds=0.02,
                )
            self.assertIn("Timed out", str(ctx.exception))
        finally:
            hold_release.set()
            t_hold.join(timeout=2.0)

    def test_resume_after_interruption_with_file_checkpoint_store(self) -> None:
        """
        Simulate process interruption using FileCheckpointStore on disk:
        pause after step_1, reconstruct a fresh WorkflowExecutor from disk, and resume.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            file_store = FileCheckpointStore(tmpdir)
            plan = WorkflowPlan(
                workflow_id="wf-interrupted",
                goal="Survive interruption via FileCheckpointStore",
                steps=[
                    WorkflowStep(
                        step_id="step_1",
                        tool_name="academic_lookup",
                        input_payload={"record_type": "student", "record_id": "S101"},
                    ),
                    WorkflowStep(
                        step_id="step_2",
                        tool_name="academic_lookup",
                        input_payload={"record_type": "course", "record_id": "$step_1.enrolled_courses[0]"},
                        dependencies=["step_1"],
                    ),
                ],
            )

            exec1 = WorkflowExecutor(plan=plan, registry=self.registry, checkpoint_store=file_store)
            # Simulate step_1 completing before interruption/pause
            exec1.state_machine.transition_to(WorkflowState.RUNNING)
            step1 = plan.get_step("step_1")
            step1.status = "completed"
            step1.result = WorkflowResult.ok({"student_id": "S101", "enrolled_courses": ["CS101"]})
            exec1.pause(reason="Simulated worker restart")

            latest = file_store.get_latest("wf-interrupted")
            self.assertIsNotNone(latest)
            assert latest is not None

            # Fresh executor instance loaded solely from disk checkpoint
            fresh_registry = create_default_registry()
            exec2 = WorkflowExecutor.from_checkpoint(
                latest.checkpoint_id,
                checkpoint_store=file_store,
                registry=fresh_registry,
            )
            res = exec2.resume_from_checkpoint(latest.checkpoint_id)
            self.assertTrue(res.success)
            self.assertEqual(exec2.current_state, WorkflowState.SUCCEEDED)
            # Only step_2 ran on the resumed worker (step_1 was NOT re-executed)
            self.assertEqual(fresh_registry.get_invocation_count("academic_lookup"), 1)
            self.assertEqual(exec2.plan.get_step("step_2").result.output["course_id"], "CS101")


if __name__ == "__main__":
    unittest.main()
