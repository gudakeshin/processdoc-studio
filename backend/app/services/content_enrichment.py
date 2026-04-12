from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class UserIntent(str, Enum):
    RISK_FOCUSED = "risk"
    VALUE_FOCUSED = "value"
    CAPABILITY_FOCUSED = "capability"
    COMPLIANCE_FOCUSED = "compliance"
    GENERAL = "general"


@dataclass
class ProcessAnalytics:
    steps_count: int = 0
    roles_count: int = 0
    decision_points: int = 0


@dataclass
class RiskProfile:
    risks: list[dict[str, Any]]
    controls: list[str]


@dataclass
class ContentEnrichment:
    user_intent: UserIntent
    audience_type: str
    process_analytics: ProcessAnalytics
    risk_profile: RiskProfile
    value_drivers: list[dict[str, Any]]
    context_snippets: str


class ContentEnrichmentEngine:
    def enrich(self, user_instruction: str, process_model: dict[str, Any], prior_artifacts: dict[str, Any]) -> ContentEnrichment:
        intent = self._classify_intent(user_instruction)
        audience = self._infer_audience(user_instruction)
        analytics = ProcessAnalytics(
            steps_count=len(process_model.get("steps", [])) if isinstance(process_model, dict) else 0,
            roles_count=len(set(s.get("role") for s in process_model.get("steps", []) if isinstance(s, dict))) if isinstance(process_model, dict) else 0,
            decision_points=len(process_model.get("decisions", [])) if isinstance(process_model, dict) else 0,
        )
        risks = process_model.get("risks", []) if isinstance(process_model, dict) and isinstance(process_model.get("risks"), list) else []
        controls = [str(c).strip() for c in (process_model.get("controls") or []) if str(c).strip()] if isinstance(process_model, dict) else []
        value_drivers = process_model.get("improvement_opportunities", []) if isinstance(process_model, dict) and isinstance(process_model.get("improvement_opportunities"), list) else []
        parts: list[str] = []
        for k in ("narrative", "docx", "pdf"):
            v = prior_artifacts.get(k) if isinstance(prior_artifacts, dict) else None
            if isinstance(v, str) and v.strip():
                parts.append(v.strip()[:1200])
        return ContentEnrichment(
            user_intent=intent,
            audience_type=audience,
            process_analytics=analytics,
            risk_profile=RiskProfile(risks=risks, controls=controls),
            value_drivers=value_drivers[:5],
            context_snippets="\n\n".join(parts)[:4000],
        )

    def _classify_intent(self, instruction: str) -> UserIntent:
        t = (instruction or "").lower()
        if any(k in t for k in ("risk", "mitigation", "failure", "contingency")):
            return UserIntent.RISK_FOCUSED
        if any(k in t for k in ("cost", "roi", "benefit", "efficiency", "savings")):
            return UserIntent.VALUE_FOCUSED
        if any(k in t for k in ("capability", "maturity", "strength")):
            return UserIntent.CAPABILITY_FOCUSED
        if any(k in t for k in ("compliance", "regulatory", "audit", "governance")):
            return UserIntent.COMPLIANCE_FOCUSED
        return UserIntent.GENERAL

    def _infer_audience(self, instruction: str) -> str:
        t = (instruction or "").lower()
        if "executive" in t or "board" in t:
            return "executive"
        if "operations" in t or "team" in t:
            return "operational"
        return "general"

