"""Seven-stage run permission pipeline (v2: effective readiness)."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
from typing import Any

from app.core.config import settings


@dataclass
class PermissionDecision:
    allowed: bool
    stage: str
    code: str = "ok"
    reason: str = ""
    metadata: dict[str, Any] | None = None
    warnings: list[str] | None = None


def _extract_nodes(plan_obj: dict[str, Any]) -> list | None:
    """Extract contract_nodes from plan payload (top-level or nested under run_contract)."""
    nodes = plan_obj.get("contract_nodes")
    if not isinstance(nodes, list):
        run_contract = plan_obj.get("run_contract")
        if isinstance(run_contract, dict):
            nodes = run_contract.get("nodes")
    return nodes if isinstance(nodes, list) else None


class PolicyEvaluator:
    """Pluggable policy classifier for stage 6 (v2: effective readiness)."""

    def __init__(self, bundle: dict[str, Any] | None = None) -> None:
        self._bundle = bundle or load_policy_bundle()

    def evaluate(
        self,
        *,
        outputs: list[str],
        run_status: str,
        plan_payload: dict[str, Any] | None = None,
        agentic_loop_enabled: bool = False,
    ) -> tuple[float, str, list[str]]:
        """Evaluate plan readiness.

        Returns (score, reason, warnings).
        Score >= threshold → allowed.  Warnings are advisory-only.
        """
        _ = run_status
        warnings: list[str] = []

        # Hard gate: forbidden outputs
        deny_outputs = set(str(x).strip() for x in (self._bundle.get("deny_outputs") or []))
        if not deny_outputs:
            deny_outputs = {"root_shell", "raw_bash"}
        if any(o in deny_outputs for o in outputs):
            return 0.0, "policy_forbidden_output", []

        plan_obj = plan_payload if isinstance(plan_payload, dict) else {}

        # Effective check: does the plan have substance?
        has_instruction = bool(
            plan_obj.get("instruction")
            or plan_obj.get("raw_text")
            or plan_obj.get("plan_summary")
            or plan_obj.get("skill_card")
            or plan_obj.get("sub_agents")
        )

        # Contract nodes (context-dependent)
        require_nodes = bool(self._bundle.get("require_contract_nodes", False))
        nodes = _extract_nodes(plan_obj)
        has_nodes = isinstance(nodes, list) and len(nodes) > 0

        if agentic_loop_enabled:
            # Agentic loop builds its own task board; nodes are informational only
            if not has_nodes:
                warnings.append("contract_nodes_empty_agentic_mode_ok")
        elif require_nodes and not has_nodes:
            # Legacy mode with strict setting: hard gate
            return 0.4, "policy_plan_incomplete_legacy", warnings
        elif not has_nodes:
            # Legacy mode, default: advisory warning only
            warnings.append("contract_nodes_empty_advisory")

        # Only genuinely unrunnable plans get blocked
        if not has_instruction and not has_nodes and not agentic_loop_enabled:
            return 0.3, "policy_plan_no_substance", warnings

        return 1.0, "policy_allow", warnings

    def version(self) -> str:
        return str(self._bundle.get("version") or settings.policy_evaluator_version)

    def rule_id(self, reason: str) -> str:
        mapping = {
            "policy_forbidden_output": "rule.forbidden_output",
            "policy_plan_incomplete": "rule.plan_incomplete",
            "policy_plan_incomplete_legacy": "rule.plan_incomplete",
            "policy_plan_no_substance": "rule.plan_no_substance",
            "policy_allow": "rule.allow_default",
        }
        return mapping.get(reason, "rule.allow_default")

    def decision_path(self) -> list[str]:
        return [
            "input_validation",
            "deny_rules",
            "allow_rules",
            "tool_specific_checks",
            "hooks_precheck",
            "policy_classifier_gate",
        ]


def load_policy_bundle() -> dict[str, Any]:
    base: dict[str, Any] = {
        "version": settings.policy_evaluator_version,
        "deny_outputs": ["root_shell", "raw_bash"],
        "require_contract_nodes": bool(getattr(settings, "policy_require_contract_nodes", False)),
    }
    raw = (settings.policy_bundle_path or "").strip()
    if not raw:
        return base
    try:
        obj = json.loads(Path(raw).read_text(encoding="utf-8"))
    except Exception:
        return base
    if not isinstance(obj, dict):
        return base
    merged = {**base, **obj}
    return merged


def evaluate_permission_pipeline(
    *,
    run_status: str,
    has_approval: bool,
    requested_outputs: list[str],
    workspace_ready: bool = True,
    classifier_score: float = 1.0,
    classifier_threshold: float = 0.5,
    policy_evaluator: PolicyEvaluator | None = None,
    enforce_policy: bool = True,
    plan_payload: dict[str, Any] | None = None,
    include_human_gate: bool = True,
    agentic_loop_enabled: bool = False,
) -> list[PermissionDecision]:
    """
    Seven-stage permission gate (v2: effective readiness).
    Each stage emits a decision record for timeline/audit purposes.
    """
    outputs = [str(x).strip() for x in (requested_outputs or []) if str(x).strip()]
    out_count = len(outputs)
    decisions: list[PermissionDecision] = []

    # 1) Input validation
    valid_inputs = out_count > 0
    decisions.append(
        PermissionDecision(
            allowed=valid_inputs,
            stage="input_validation",
            code="ok" if valid_inputs else "input.no_outputs",
            reason="" if valid_inputs else "no_requested_outputs",
            metadata={"requested_output_count": out_count},
        )
    )
    if not valid_inputs:
        return decisions

    # 2) Deny rules
    deny_hit = any(o in {"root_shell", "raw_bash"} for o in outputs)
    decisions.append(
        PermissionDecision(
            allowed=not deny_hit,
            stage="deny_rules",
            code="ok" if not deny_hit else "deny.forbidden_output",
            reason="" if not deny_hit else "forbidden_output_requested",
            metadata={"forbidden_requested": deny_hit},
        )
    )
    if deny_hit:
        return decisions

    # 3) Allow rules
    allow_hit = all(o in {"process_map", "docx", "pptx", "xlsx", "pdf", "narrative", "raci", "sop"} for o in outputs)
    decisions.append(
        PermissionDecision(
            allowed=allow_hit,
            stage="allow_rules",
            code="ok" if allow_hit else "allow.unknown_output_type",
            reason="" if allow_hit else "unknown_output_type",
            metadata={"outputs": outputs},
        )
    )
    if not allow_hit:
        return decisions

    # 4) Tool/stage-specific checks
    decisions.append(
        PermissionDecision(
            allowed=workspace_ready,
            stage="tool_specific_checks",
            code="ok" if workspace_ready else "workspace.not_ready",
            reason="" if workspace_ready else "workspace_not_ready",
        )
    )
    if not workspace_ready:
        return decisions

    # 5) Hooks pre-check (hook execution itself happens elsewhere)
    decisions.append(PermissionDecision(allowed=True, stage="hooks_precheck", code="ok"))

    # Stage 6 (policy classifier gate) REMOVED.
    # Quality evaluation is the coordinator's responsibility, not a pre-execution gate.

    # 6) Human approval gate
    if not include_human_gate:
        return decisions
    approved = has_approval and run_status in {"approved", "running"}
    decisions.append(
        PermissionDecision(
            allowed=approved,
            stage="human_approval_gate",
            code="ok" if approved else "approval.missing",
            reason="" if approved else "run_not_human_approved",
            metadata={"run_status": run_status},
        )
    )
    return decisions
