"""
Plan Validator for W4 Agentic Workflow.

Provides static validation for WorkflowPlan objects prior to execution:
- Structural validation (IDs, goal, non-empty step list)
- Duplicate step ID detection
- Allow-listed tool verification against ToolRegistry
- Input parameter conformance against ToolSpec schema
- Dependency reference integrity and self-dependency rejection
- DAG circular dependency detection using Depth-First Search (DFS)
"""

from __future__ import annotations

from typing import Dict, List, Optional, Set
from .schemas import WorkflowPlan, WorkflowStep, ToolSpec
from .mock_tools import ToolRegistry


class PlanValidationError(ValueError):
    """Exception raised when a workflow plan fails static validation."""
    pass


class PlanValidator:
    """
    Static analyzer validating WorkflowPlan structures, tool references,
    parameter schemas, and acyclic dependency graphs (DAGs).
    """

    def __init__(self, registry: Optional[ToolRegistry] = None) -> None:
        self.registry = registry

    def validate(self, plan: WorkflowPlan) -> None:
        """
        Validate a WorkflowPlan.
        Raises PlanValidationError on any validation failure.
        """
        self._validate_structure(plan)
        self._validate_steps(plan)
        self._validate_dependencies(plan)
        self._validate_dag(plan)

    def _validate_structure(self, plan: WorkflowPlan) -> None:
        """Check top-level structure and non-empty properties."""
        if not isinstance(plan, WorkflowPlan):
            raise PlanValidationError(f"Expected WorkflowPlan instance, got {type(plan).__name__}.")

        if not plan.workflow_id or not str(plan.workflow_id).strip():
            raise PlanValidationError("WorkflowPlan must have a non-empty 'workflow_id'.")

        if not plan.goal or not str(plan.goal).strip():
            raise PlanValidationError("WorkflowPlan must have a non-empty 'goal'.")

        if not plan.steps or not isinstance(plan.steps, list):
            raise PlanValidationError("WorkflowPlan must contain at least one step in 'steps'.")

    def _validate_steps(self, plan: WorkflowPlan) -> None:
        """Check step uniqueness, valid tool names, and parameter schemas."""
        seen_step_ids: Set[str] = set()

        for idx, step in enumerate(plan.steps):
            if not isinstance(step, WorkflowStep):
                raise PlanValidationError(f"Step at index {idx} must be a WorkflowStep instance.")

            if not step.step_id or not str(step.step_id).strip():
                raise PlanValidationError(f"Step at index {idx} has an empty 'step_id'.")

            if step.step_id in seen_step_ids:
                raise PlanValidationError(f"Duplicate step_id detected: '{step.step_id}'.")
            seen_step_ids.add(step.step_id)

            if not step.tool_name or not str(step.tool_name).strip():
                raise PlanValidationError(f"Step '{step.step_id}' must specify a non-empty 'tool_name'.")

            # Validate against tool registry if provided
            if self.registry is not None:
                if not self.registry.has_tool(step.tool_name):
                    raise PlanValidationError(
                        f"Step '{step.step_id}' specifies unregistered tool '{step.tool_name}'. "
                        f"Registered tools: {[s.name for s in self.registry.list_specs()]}."
                    )
                spec = self.registry.get_spec(step.tool_name)
                self._validate_parameters(step, spec)

    def _validate_parameters(self, step: WorkflowStep, spec: ToolSpec) -> None:
        """Validate input payload against ToolSpec parameters_schema."""
        schema = spec.parameters_schema
        payload = step.input_payload or {}

        for param_name, param_rule in schema.items():
            is_required = param_rule.get("required", False)
            if is_required and param_name not in payload:
                raise PlanValidationError(
                    f"Step '{step.step_id}' missing required parameter '{param_name}' for tool '{spec.name}'."
                )

            if param_name in payload:
                val = payload[param_name]
                expected_type = param_rule.get("type")
                if expected_type == "str" and not isinstance(val, str):
                    raise PlanValidationError(
                        f"Step '{step.step_id}' parameter '{param_name}' must be a str, got {type(val).__name__}."
                    )
                elif expected_type == "int" and (not isinstance(val, int) or isinstance(val, bool)):
                    raise PlanValidationError(
                        f"Step '{step.step_id}' parameter '{param_name}' must be an int, got {type(val).__name__}."
                    )

                allowed_values = param_rule.get("allowed_values")
                if allowed_values and val not in allowed_values:
                    raise PlanValidationError(
                        f"Step '{step.step_id}' parameter '{param_name}' value '{val}' not in allowed values: {allowed_values}."
                    )

    def _validate_dependencies(self, plan: WorkflowPlan) -> None:
        """Verify that dependencies exist and reject self-dependencies."""
        step_ids = {s.step_id for s in plan.steps}

        for step in plan.steps:
            for dep in step.dependencies:
                if dep == step.step_id:
                    raise PlanValidationError(
                        f"Step '{step.step_id}' cannot depend on itself (self-dependency detected)."
                    )
                if dep not in step_ids:
                    raise PlanValidationError(
                        f"Step '{step.step_id}' has unknown dependency '{dep}'. Known steps: {sorted(step_ids)}."
                    )

    def _validate_dag(self, plan: WorkflowPlan) -> None:
        """
        Verify that the step dependency graph contains no cycles using DFS (3-color cycle detection).
        WHITE = 0 (unvisited), GRAY = 1 (visiting / on current recursion stack), BLACK = 2 (visited).
        """
        adjacency: Dict[str, List[str]] = {s.step_id: list(s.dependencies) for s in plan.steps}
        state: Dict[str, int] = {s.step_id: 0 for s in plan.steps}

        def dfs(node: str, path: List[str]) -> None:
            state[node] = 1  # GRAY: visiting
            path.append(node)

            for dep in adjacency.get(node, []):
                if state[dep] == 1:
                    # Found back-edge -> cycle!
                    cycle_start_idx = path.index(dep)
                    cycle_chain = " -> ".join(path[cycle_start_idx:] + [dep])
                    raise PlanValidationError(f"Circular dependency detected in plan: {cycle_chain}.")
                elif state[dep] == 0:
                    dfs(dep, path)

            path.pop()
            state[node] = 2  # BLACK: completely processed

        for step in plan.steps:
            if state[step.step_id] == 0:
                dfs(step.step_id, [])
