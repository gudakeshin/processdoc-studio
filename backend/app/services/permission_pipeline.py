"""Seven-stage run permission pipeline."""

from __future__ import annotations

from dataclasses import dataclass
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


class PolicyEvaluator:
    """Pluggable policy classifier for stage 6."""

    def __init__(self, bundle: dict[str, Any] | None = None) -> None:
        self._bundle = bundle or load_policy_bundle()

    def evaluate(self, *, outputs: list[str], run_status: str, plan_payload: dict[str, Any] | None = None) -> tuple[float, str]:
        _ = run_status
        deny_outputs = set(str(x).strip() for x in (self._bundle.get("deny_outputs") or []))
        if not deny_outputs:
            deny_outputs = {"root_shell", "raw_bash"}
        if any(o in deny_outputs for o in outputs):
            return 0.0, "policy_forbidden_output"
        plan_obj = plan_payload if isinstance(plan_payload, dict) else {}
        nodes = plan_obj.get("contract_nodes")
        if not isinstance(nodes, list):
            run_contract = plan_obj.get("run_contract") if isinstance(plan_obj.get("run_contract"), dict) else {}
            nodes = run_contract.get("nodes")
        has_nodes = isinstance(nodes, list) and len(nodes or []) > 0
        coverage = bool(plan_obj.get("acceptance_criteria_coverage")) or has_nodes
        if (not coverage) or (not has_nodes):
            return 0.4, "policy_plan_incomplete"
        return 1.0, "policy_allow"

    def version(self) -> str:
        return str(self._bundle.get("version") or settings.policy_evaluator_version)

    def rule_id(self, reason: str) -> str:
        if reason == "policy_forbidden_output":
            return "rule.forbidden_output"
        if reason == "policy_plan_incomplete":
            return "rule.plan_incomplete"
        return "rule.allow_default"

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
) -> list[PermissionDecision]:
    """
    Lightweight seven-stage permission gate.
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

    # 6) Policy/model classifier gate
    evaluator = policy_evaluator or PolicyEvaluator()
    eval_score, eval_reason = evaluator.evaluate(outputs=outputs, run_status=run_status, plan_payload=plan_payload)
    effective_score = min(float(classifier_score), float(eval_score))
    cls_allowed = effective_score >= float(classifier_threshold)
    if not enforce_policy:
        cls_allowed = True
    policy_hash = hashlib.sha256(
        f"{evaluator.version()}::{evaluator.rule_id(eval_reason)}::{eval_reason}".encode("utf-8")
    ).hexdigest()[:16]
    decisions.append(
        PermissionDecision(
            allowed=cls_allowed,
            stage="policy_classifier_gate",
            code="ok" if cls_allowed else "classifier.below_threshold",
            reason="" if cls_allowed else "classifier_rejected",
            metadata={
                "score": effective_score,
                "threshold": float(classifier_threshold),
                "policy_reason": eval_reason,
                "policy_version": evaluator.version(),
                "rule_id": evaluator.rule_id(eval_reason),
                "policy_hash": policy_hash,
                "matched_rules": [evaluator.rule_id(eval_reason)],
                "decision_path": evaluator.decision_path(),
                "enforcement_mode": "enforce" if enforce_policy else "dry_run",
            },
        )
    )
    if not cls_allowed:
        return decisions

    # 7) Human approval gate
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

