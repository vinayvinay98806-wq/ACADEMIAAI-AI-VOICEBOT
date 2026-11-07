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
    parameter schemas, permission scopes, acyclic dependency graphs (DAGs),
    and execution order consistency.
    """

    def __init__(self, registry: Optional[ToolRegistry] = None) -> None:
        self.registry = registry

    def validate(
        self,
        plan: WorkflowPlan,
        authorized_permissions: Optional[Set[str] | List[str]] = None,
    ) -> None:
        """
        Validate a WorkflowPlan.
        Raises PlanValidationError on any validation failure.
        """
        self._validate_structure(plan)
        self._validate_steps(plan, authorized_permissions=authorized_permissions)
        self._validate_dependencies(plan)
        self._validate_dag(plan)
        self._validate_execution_order(plan)

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

    def _validate_steps(
        self,
        plan: WorkflowPlan,
        authorized_permissions: Optional[Set[str] | List[str]] = None,
    ) -> None:
        """Check step uniqueness, valid tool names, parameter schemas, and permission scopes."""
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

                # Validate permission scopes if authorized_permissions is specified
                if authorized_permissions is not None:
                    perm_ok, perm_err = self.registry.check_permissions(step.tool_name, authorized_permissions)
                    if not perm_ok:
                        raise PlanValidationError(
                            f"Permission-scope violation for step '{step.step_id}': {perm_err}"
                        )

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
                # If value is a dynamic reference like '$step_id.key' or '{{step_id.key}}', skip static type check
                if isinstance(val, str) and (val.startswith("$") or (val.startswith("{{") and val.endswith("}}"))):
                    continue

                expected_type = param_rule.get("type")
                if expected_type == "str" and not isinstance(val, str):
                    raise PlanValidationError(
                        f"Step '{step.step_id}' parameter '{param_name}' must be a str, got {type(val).__name__}."
                    )
                elif expected_type == "int" and (not isinstance(val, int) or isinstance(val, bool)):
                    raise PlanValidationError(
                        f"Step '{step.step_id}' parameter '{param_name}' must be an int, got {type(val).__name__}."
                    )
                elif expected_type == "float" and (not isinstance(val, (int, float)) or isinstance(val, bool)):
                    raise PlanValidationError(
                        f"Step '{step.step_id}' parameter '{param_name}' must be a float, got {type(val).__name__}."
                    )
                elif expected_type == "bool" and not isinstance(val, bool):
                    raise PlanValidationError(
                        f"Step '{step.step_id}' parameter '{param_name}' must be a bool, got {type(val).__name__}."
                    )
                elif expected_type == "list" and not isinstance(val, list):
                    raise PlanValidationError(
                        f"Step '{step.step_id}' parameter '{param_name}' must be a list, got {type(val).__name__}."
                    )
                elif expected_type == "dict" and not isinstance(val, dict):
                    raise PlanValidationError(
                        f"Step '{step.step_id}' parameter '{param_name}' must be a dict, got {type(val).__name__}."
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

    def _validate_execution_order(self, plan: WorkflowPlan) -> None:
        """
        Validate that steps appear in executable topological order:
        Every prerequisite dependency must appear before the dependent step in the plan step sequence.
        """
        step_indices: Dict[str, int] = {step.step_id: idx for idx, step in enumerate(plan.steps)}

        for idx, step in enumerate(plan.steps):
            for dep in step.dependencies:
                dep_idx = step_indices.get(dep)
                if dep_idx is not None and dep_idx > idx:
                    raise PlanValidationError(
                        f"Execution order violation: Step '{step.step_id}' (position {idx}) depends on step '{dep}' "
                        f"(position {dep_idx}), which appears after it in execution sequence."
                    )

    def get_topological_order(self, plan: WorkflowPlan) -> List[str]:
        """
        Calculate and return a valid topological execution order for the steps in the plan.
        Raises PlanValidationError if dependencies are invalid or contain a cycle.
        """
        self._validate_dependencies(plan)
        self._validate_dag(plan)

        in_degree: Dict[str, int] = {s.step_id: 0 for s in plan.steps}
        dependents: Dict[str, List[str]] = {s.step_id: [] for s in plan.steps}

        for step in plan.steps:
            for dep in step.dependencies:
                dependents[dep].append(step.step_id)
                in_degree[step.step_id] += 1

        queue: List[str] = [step_id for step_id, deg in in_degree.items() if deg == 0]
        order: List[str] = []

        while queue:
            curr = queue.pop(0)
            order.append(curr)
            for nxt in dependents[curr]:
                in_degree[nxt] -= 1
                if in_degree[nxt] == 0:
                    queue.append(nxt)

        if len(order) != len(plan.steps):
            raise PlanValidationError("Could not determine complete topological ordering due to cycle.")

        return order
