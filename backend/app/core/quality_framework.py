from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional, Union

logger = logging.getLogger(__name__)


class QualityDimension(str, Enum):
    CONTENT_QUALITY = "content_quality"
    NARRATIVE_COHERENCE = "narrative_coherence"
    BRANDING_COMPLIANCE = "branding_compliance"


@dataclass
class QualityResult:
    score: float
    issues: list[str]
    remediation_hint: str | None = None


class QualityRule(ABC):
    dimension: QualityDimension
    applicable_output_types: set[str]

    @abstractmethod
    def evaluate(self, output_type: str, text: str, metadata: dict[str, Any], context: dict[str, Any]) -> QualityResult:
        raise NotImplementedError


class NarrativeCoherenceRule(QualityRule):
    dimension = QualityDimension.NARRATIVE_COHERENCE
    applicable_output_types = {"pptx", "docx", "pdf"}

    def evaluate(self, output_type: str, text: str, metadata: dict[str, Any], context: dict[str, Any]) -> QualityResult:
        lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
        score = 1.0 if len(lines) >= 3 else 0.65
        issues = [] if score >= 0.75 else ["Narrative appears too thin; increase structure and progression."]
        hint = None if score >= 0.75 else "Add a clear beginning-middle-end arc and make transitions explicit."
        return QualityResult(score=score, issues=issues, remediation_hint=hint)


class BrandingComplianceRule(QualityRule):
    dimension = QualityDimension.BRANDING_COMPLIANCE
    applicable_output_types = {"pptx", "docx", "pdf", "xlsx"}

    def evaluate(self, output_type: str, text: str, metadata: dict[str, Any], context: dict[str, Any]) -> QualityResult:
        branding = context.get("branding") if isinstance(context, dict) else None
        primary = str(getattr(branding, "primary_color", "") or "").strip()
        if not primary:
            return QualityResult(
                score=0.8,
                issues=["Branding context missing primary color."],
                remediation_hint="Resolve branding context before rendering deliverables.",
            )
        return QualityResult(score=1.0, issues=[], remediation_hint=None)


class ContentQualityRule(QualityRule):
    dimension = QualityDimension.CONTENT_QUALITY
    applicable_output_types = {"pptx", "docx", "pdf", "xlsx"}

    def evaluate(self, output_type: str, text: str, metadata: dict[str, Any], context: dict[str, Any]) -> QualityResult:
        score = 1.0 if len((text or "").strip()) >= 80 else 0.7
        issues = [] if score >= 0.75 else ["Content volume is low; add concrete details and metrics."]
        hint = None if score >= 0.75 else "Increase specificity with concrete metrics, risks, and next actions."
        return QualityResult(score=score, issues=issues, remediation_hint=hint)


class EvaluatorKind(ABC):
    """Base class for pluggable evaluator kinds (section_coverage, citation_density, etc.)"""

    @abstractmethod
    def evaluate(
        self,
        text: str,
        dimension_config: dict[str, Any],
    ) -> tuple[float, dict[str, Any]]:
        """Evaluate text against dimension config.

        Returns: (score: float 0-1, metadata: dict)
        """
        pass


class EvaluatorRegistry:
    """Registry for pluggable evaluator kinds."""

    _evaluators: dict[str, type[EvaluatorKind]] = {}

    @classmethod
    def register(cls, kind: str, evaluator_class: type[EvaluatorKind]) -> None:
        """Register an evaluator kind."""
        cls._evaluators[str(kind).lower()] = evaluator_class
        logger.info(f"Registered evaluator kind: {kind}")

    @classmethod
    def get(cls, kind: str) -> Optional[type[EvaluatorKind]]:
        """Get an evaluator kind by name."""
        return cls._evaluators.get(str(kind).lower())

    @classmethod
    def all(cls) -> dict[str, type[EvaluatorKind]]:
        """Get all registered evaluator kinds."""
        return dict(cls._evaluators)


class ContractRuleFactory:
    """Factory to create QualityRule instances from JSON contract dimensions."""

    @staticmethod
    def create_rule_from_dimension(dimension_config: dict[str, Any]) -> Optional[QualityRule]:
        """Create a QualityRule from a contract dimension JSON.

        Args:
            dimension_config: Dict with 'kind', 'id', 'weight', output_types, etc.

        Returns:
            QualityRule instance, or None if invalid
        """
        kind = dimension_config.get("kind")
        if not kind:
            logger.warning("Dimension config missing 'kind'")
            return None

        dimension_id = dimension_config.get("id") or str(kind)
        weight = float(dimension_config.get("weight", 0.33))
        output_types = set(dimension_config.get("output_types", []))
        if not output_types:
            output_types = {"pptx", "docx", "pdf", "xlsx"}

        # Create dynamic rule class
        class ContractRule(QualityRule):
            dimension = QualityDimension.CONTENT_QUALITY  # Default for contract-based rules
            applicable_output_types = output_types

            def evaluate(
                self,
                output_type: str,
                text: str,
                metadata: dict[str, Any],
                context: dict[str, Any],
            ) -> QualityResult:
                # Try to evaluate using registered evaluator
                evaluator_class = EvaluatorRegistry.get(kind)
                if evaluator_class:
                    try:
                        evaluator = evaluator_class()
                        score, metadata_out = evaluator.evaluate(text, dimension_config)
                        return QualityResult(score=score, issues=[], remediation_hint=None)
                    except Exception as e:
                        logger.warning(f"Evaluator {kind} failed: {e}")
                        return QualityResult(score=0.5, issues=[f"Evaluator error: {str(e)}"])

                # Fallback: basic text length check
                score = 1.0 if len((text or "").strip()) >= 80 else 0.6
                return QualityResult(
                    score=score,
                    issues=[] if score >= 0.75 else ["Content length low"],
                )

        return ContractRule()


class UnifiedQualityFramework:
    def __init__(self, include_contract_rules: bool = False) -> None:
        self.rules: list[QualityRule] = [
            NarrativeCoherenceRule(),
            BrandingComplianceRule(),
            ContentQualityRule(),
        ]
        self.include_contract_rules = include_contract_rules

    def add_rule(self, rule: QualityRule) -> None:
        """Add a quality rule dynamically."""
        self.rules.append(rule)

    def add_contract_rules(self, contracts: dict[str, dict[str, Any]]) -> None:
        """Add rules from contract dimensions."""
        for contract_key, contract_data in contracts.items():
            if not isinstance(contract_data, dict):
                continue
            dimensions = contract_data.get("dimensions")
            if not isinstance(dimensions, list):
                continue
            for dim_config in dimensions:
                rule = ContractRuleFactory.create_rule_from_dimension(dim_config)
                if rule:
                    self.add_rule(rule)
                    logger.debug(f"Added contract rule from {contract_key}")

    def evaluate_deliverable(
        self,
        output_type: str,
        text: str,
        metadata: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        dimensions: dict[str, dict[str, Any]] = {}
        for rule in self.rules:
            if output_type not in rule.applicable_output_types:
                continue
            try:
                result = rule.evaluate(output_type, text, metadata, context)
                dimensions[rule.dimension.value] = {
                    "score": max(0.0, min(1.0, float(result.score))),
                    "issues": list(result.issues),
                    "remediation_hint": result.remediation_hint,
                }
            except Exception as e:
                logger.error(f"Rule evaluation failed for {rule.dimension}: {e}")
                dimensions[rule.dimension.value] = {
                    "score": 0.5,
                    "issues": [f"Evaluation error: {str(e)}"],
                    "remediation_hint": None,
                }

        aggregate = (
            sum(d["score"] for d in dimensions.values()) / len(dimensions)
            if dimensions
            else 1.0
        )
        return {
            "output_type": output_type,
            "aggregate_score": aggregate,
            "dimensions": dimensions,
            "passed": aggregate >= 0.75,
            "threshold": 0.75,
        }


# Register built-in evaluator kinds
# (These are registered automatically on module import)
def _register_builtin_evaluators() -> None:
    """Register built-in evaluator implementations."""
    try:
        from .evaluators import (
            CitationDensityEvaluator,
            CompletenessEvaluator,
            ContentLengthEvaluator,
            LLMCritiqueEvaluator,
            SectionCoverageEvaluator,
        )

        EvaluatorRegistry.register("section_coverage", SectionCoverageEvaluator)
        EvaluatorRegistry.register("citation_density", CitationDensityEvaluator)
        EvaluatorRegistry.register("llm_critique", LLMCritiqueEvaluator)
        EvaluatorRegistry.register("content_length", ContentLengthEvaluator)
        EvaluatorRegistry.register("completeness", CompletenessEvaluator)
        logger.info("Registered 5 built-in evaluator kinds")
    except ImportError as e:
        logger.warning(f"Could not register built-in evaluators: {e}")


# Auto-register on module import
_register_builtin_evaluators()
