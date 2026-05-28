from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class QualityDimension(StrEnum):
    CONTENT_QUALITY = "content_quality"
    NARRATIVE_COHERENCE = "narrative_coherence"
    BRANDING_COMPLIANCE = "branding_compliance"
    STRUCTURAL_COMPLETENESS = "structural_completeness"
    VISUAL_QUALITY = "visual_quality"


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


class StructuralCompletenessRule(QualityRule):
    """Phase 2: reuse Phase 1 PPTX slide completeness checks inside the unified framework."""

    dimension = QualityDimension.STRUCTURAL_COMPLETENESS
    applicable_output_types = {"pptx", "docx", "pdf", "xlsx"}

    def evaluate(self, output_type: str, text: str, metadata: dict[str, Any], context: dict[str, Any]) -> QualityResult:
        if output_type == "pptx":
            from app.services.deliverable_quality import _validate_pptx_completeness

            raw = (text or "").strip()
            if not raw:
                return QualityResult(score=0.0, issues=["Empty pptx_slides payload"], remediation_hint="Generate slide JSON with populated content blocks.")
            ok, issues = _validate_pptx_completeness(raw)
            if ok:
                return QualityResult(score=1.0, issues=[], remediation_hint=None)
            return QualityResult(
                score=0.0,
                issues=list(issues)[:12],
                remediation_hint="Fix slide bodies: stat_cards, column_cards, stack_layers, table, and bullets must meet minimum item counts per slide_type.",
            )

        body = (text or "").strip()
        if not body:
            return QualityResult(score=0.2, issues=["Deliverable text is empty"], remediation_hint="Add substantive content before rendering.")

        if output_type in {"docx", "pdf"}:
            has_heading = bool(body.lstrip().startswith("#")) or "\n#" in body
            if not has_heading:
                return QualityResult(
                    score=0.72,
                    issues=["No markdown headings found; structure may be too flat."],
                    remediation_hint="Use # / ## headings to organize sections.",
                )

        if output_type == "xlsx" and len(body) < 40:
            return QualityResult(
                score=0.7,
                issues=["XLSX markdown preview is very short."],
                remediation_hint="Ensure sheets and key tables are described with enough rows/columns.",
            )

        return QualityResult(score=1.0, issues=[], remediation_hint=None)


class VisualQualityRule(QualityRule):
    """Deterministic visual/layout heuristics for PPTX slide JSON."""

    dimension = QualityDimension.VISUAL_QUALITY
    applicable_output_types = {"pptx"}

    def evaluate(self, output_type: str, text: str, metadata: dict[str, Any], context: dict[str, Any]) -> QualityResult:
        del output_type, metadata, context  # rule currently uses only slide payload
        raw = (text or "").strip()
        if not raw:
            return QualityResult(
                score=0.6,
                issues=["Missing slide payload for visual quality checks."],
                remediation_hint="Generate slides first, then run visual QA.",
            )
        try:
            payload = json.loads(raw)
        except Exception:
            return QualityResult(
                score=0.6,
                issues=["Slide payload is not valid JSON for visual checks."],
                remediation_hint="Return parseable JSON with a top-level slides array.",
            )
        slides = payload.get("slides") if isinstance(payload, dict) else payload
        if not isinstance(slides, list) or not slides:
            return QualityResult(
                score=0.65,
                issues=["No slides found for visual quality checks."],
                remediation_hint="Return at least one populated slide object.",
            )

        issues: list[str] = []
        allowed_stat_fills = {"dark", "mid_dark", "gray"}
        allowed_column_accents = {"green", "dark", "gray"}
        allowed_layer_fills = {"green", "dark", "mid_dark", "gray", "mid", "dark_green"}

        for idx, raw_slide in enumerate(slides, start=1):
            if not isinstance(raw_slide, dict):
                issues.append(f"Slide {idx}: invalid slide object.")
                continue
            title = str(raw_slide.get("title") or "").strip()
            if not title:
                issues.append(f"Slide {idx}: missing title.")
            elif len(title.split()) > 12:
                issues.append(f"Slide {idx}: title too long for visual hierarchy.")

            # Rough text-density estimate catches cluttered slides before render.
            density_words = len(title.split())
            for key in ("subtitle", "footer_note"):
                density_words += len(str(raw_slide.get(key) or "").split())

            bullets = raw_slide.get("bullets")
            if isinstance(bullets, list):
                if len(bullets) > 5:
                    issues.append(f"Slide {idx}: too many bullets ({len(bullets)}); cap at 5 for executive decks.")
                for bullet in bullets:
                    word_count = len(str(bullet or "").split())
                    density_words += word_count
                    if word_count > 15:
                        issues.append(f"Slide {idx}: bullet too long ({word_count} words); keep to 15 words max.")

            stat_cards = raw_slide.get("stat_cards")
            if isinstance(stat_cards, list):
                for card in stat_cards:
                    if not isinstance(card, dict):
                        continue
                    fill = str(card.get("fill") or "").strip().lower()
                    if fill and fill not in allowed_stat_fills:
                        issues.append(f"Slide {idx}: stat card uses non-standard fill '{fill}'.")
                    desc_words = len(str(card.get("description") or "").split())
                    density_words += desc_words + len(str(card.get("label") or "").split())
                    if desc_words > 24:
                        issues.append(f"Slide {idx}: stat card description too long.")

            column_cards = raw_slide.get("column_cards")
            if isinstance(column_cards, list):
                for card in column_cards:
                    if not isinstance(card, dict):
                        continue
                    accent = str(card.get("accent") or "").strip().lower()
                    if accent and accent not in allowed_column_accents:
                        issues.append(f"Slide {idx}: column card uses non-standard accent '{accent}'.")
                    body_words = len(str(card.get("body") or "").split())
                    density_words += body_words + len(str(card.get("heading") or "").split())
                    if body_words > 45:
                        issues.append(f"Slide {idx}: column card body too dense.")

            layers = raw_slide.get("stack_layers")
            if isinstance(layers, list):
                for layer in layers:
                    if not isinstance(layer, dict):
                        continue
                    fill = str(layer.get("fill") or "").strip().lower()
                    if fill and fill not in allowed_layer_fills:
                        issues.append(f"Slide {idx}: stack layer uses non-standard fill '{fill}'.")
                    density_words += len(str(layer.get("description") or "").split())

            table = raw_slide.get("table")
            if isinstance(table, dict):
                rows = table.get("rows")
                if isinstance(rows, list) and len(rows) > 12:
                    issues.append(f"Slide {idx}: table has too many rows ({len(rows)}).")
                if isinstance(rows, list):
                    for row in rows:
                        if isinstance(row, list):
                            density_words += sum(len(str(cell or "").split()) for cell in row)

            if density_words > 100:
                issues.append(f"Slide {idx}: content density is high ({density_words} words); target ≤100 for readable executive slides.")

        if not issues:
            return QualityResult(score=1.0, issues=[], remediation_hint=None)

        score = max(0.35, 1.0 - (0.13 * len(issues)))
        return QualityResult(
            score=score,
            issues=issues[:20],
            remediation_hint=(
                "Reduce text density, keep headings concise, and stay within approved fill/accent palette "
                "to improve layout readability."
            ),
        )


class NarrativeCoherenceRule(QualityRule):
    """Deterministic narrative coherence checks for markdown-style outputs.

    Signals evaluated (all local / offline):

    - Document has at least a minimum number of substantive lines.
    - At least one top-level heading is present.
    - Headings show progression (no heading-only skeleton, no duplicate headings).
    - Paragraph density (non-bullet prose) meets a floor.
    - Transition words appear at least once in prose bodies.
    - Topic drift heuristic: overlap between consecutive section bodies is non-zero.

    Each failed signal adds an issue and subtracts from the score. A perfect
    narrative produces score ``1.0``; a markdown blob that is only headings, or
    only bullets, or extremely short, falls below the ``0.75`` gate and
    triggers remediation hints.
    """

    dimension = QualityDimension.NARRATIVE_COHERENCE
    applicable_output_types = {"docx", "pdf"}

    _TRANSITION_WORDS = frozenset(
        {
            "however",
            "therefore",
            "meanwhile",
            "consequently",
            "in contrast",
            "furthermore",
            "moreover",
            "nevertheless",
            "finally",
            "as a result",
            "in summary",
            "in addition",
            "for example",
            "first",
            "second",
            "next",
            "then",
        }
    )

    def _split_sections(self, text: str) -> list[dict[str, Any]]:
        sections: list[dict[str, Any]] = []
        current_heading = ""
        current_body: list[str] = []
        for raw_line in (text or "").splitlines():
            line = raw_line.rstrip()
            stripped = line.lstrip()
            if stripped.startswith("#"):
                if current_heading or current_body:
                    sections.append({"heading": current_heading, "body": "\n".join(current_body).strip()})
                current_heading = stripped.lstrip("# ").strip()
                current_body = []
                continue
            current_body.append(line)
        if current_heading or current_body:
            sections.append({"heading": current_heading, "body": "\n".join(current_body).strip()})
        return sections

    @staticmethod
    def _word_set(body: str) -> set[str]:
        tokens = [tok.strip(".,;:!?()[]\"'`").lower() for tok in (body or "").split()]
        return {tok for tok in tokens if len(tok) > 3 and tok.isalpha()}

    @staticmethod
    def _paragraph_count(body: str) -> int:
        paragraphs = 0
        for chunk in (body or "").split("\n\n"):
            chunk_stripped = chunk.strip()
            if not chunk_stripped:
                continue
            prose_lines = [
                ln for ln in chunk_stripped.splitlines() if ln.strip() and not ln.lstrip().startswith(("-", "*", "•"))
            ]
            if prose_lines and sum(len(ln.split()) for ln in prose_lines) >= 15:
                paragraphs += 1
        return paragraphs

    def evaluate(self, output_type: str, text: str, metadata: dict[str, Any], context: dict[str, Any]) -> QualityResult:
        del metadata, context
        raw = (text or "").strip()
        issues: list[str] = []

        if not raw:
            return QualityResult(
                score=0.0,
                issues=["Narrative deliverable is empty."],
                remediation_hint="Produce a full narrative with intro, body sections, and close.",
            )

        non_empty_lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        total_words = sum(len(ln.split()) for ln in non_empty_lines)
        if total_words < 80:
            issues.append(f"Narrative is too short ({total_words} words); under 80-word floor.")

        sections = self._split_sections(raw)
        headings = [s["heading"] for s in sections if s["heading"]]
        if not headings:
            issues.append("No markdown headings found; narrative lacks section structure.")
        else:
            unique_headings = {h.lower() for h in headings if h.strip()}
            if len(unique_headings) < max(2, min(3, len(headings))):
                issues.append("Headings are duplicated or thin; each section should introduce a new theme.")

        paragraph_total = sum(self._paragraph_count(s.get("body") or "") for s in sections) or self._paragraph_count(raw)
        if paragraph_total < 2:
            issues.append("Narrative prose is too light; add paragraph-level explanation beyond bullet points.")

        lowered = raw.lower()
        if not any(marker in lowered for marker in self._TRANSITION_WORDS):
            issues.append("No transition words detected; connect ideas with 'however', 'therefore', 'finally', etc.")

        bodies = [self._word_set(s.get("body") or "") for s in sections if s.get("body")]
        bodies = [b for b in bodies if b]
        if len(bodies) >= 2:
            overlaps = []
            for a, b in zip(bodies, bodies[1:], strict=False):
                if not a or not b:
                    continue
                overlaps.append(len(a & b) / float(len(a | b)) if (a | b) else 0.0)
            if overlaps and max(overlaps) == 0.0:
                issues.append("Adjacent sections share no vocabulary; narrative may be disjointed.")

        llm_issues = self._llm_critique_blend(output_type=output_type, text=raw)
        for extra in llm_issues:
            if extra and extra not in issues:
                issues.append(extra)

        if not issues:
            return QualityResult(score=1.0, issues=[], remediation_hint=None)

        score = max(0.3, 1.0 - 0.15 * len(issues))
        return QualityResult(
            score=score,
            issues=issues[:10],
            remediation_hint=(
                "Strengthen narrative arc: add an introduction, develop each section with at least one "
                "paragraph of prose, use transition words, and ensure adjacent sections reinforce each other."
            ),
        )

    @staticmethod
    def _llm_critique_blend(output_type: str, text: str) -> list[str]:
        """Optional Claude-backed critique that augments deterministic issues.

        The blend is fail-open: any import, config, or LLM error returns ``[]``
        so the deterministic gate keeps shipping. Gated behind
        ``settings.narrative_llm_critique_enabled`` to avoid spend by default.
        """

        try:
            from app.core.config import settings
        except Exception:
            return []
        if not getattr(settings, "narrative_llm_critique_enabled", False):
            return []
        max_issues = max(1, int(getattr(settings, "narrative_llm_critique_max_issues", 4) or 4))
        try:
            from app.services.claude import claude_generate_json
        except Exception:
            return []
        snippet = (text or "").strip()
        if len(snippet) > 8000:
            snippet = snippet[:8000]
        system_prompt = (
            "You review narrative deliverables for coherence. "
            "Respond with strict JSON only."
        )
        user_prompt = (
            "You review a narrative deliverable (output type: "
            f"{output_type}) for narrative coherence.\n\n"
            "Return strict JSON: {\"issues\": [string, ...]} with at most "
            f"{max_issues} items. Each issue must be one concrete, actionable "
            "sentence describing a gap in introduction / transitions / topic "
            "continuity / close — not a generic style complaint. Return an "
            "empty list if the narrative is coherent.\n\n"
            "Narrative (truncated):\n"
            f"{snippet}"
        )
        try:
            response = claude_generate_json(
                system=system_prompt,
                user=user_prompt,
                max_tokens=400,
            )
        except Exception as exc:
            logger.debug("narrative_llm_critique_blend: LLM call failed (%s)", exc)
            return []
        if not isinstance(response, dict):
            return []
        raw_issues = response.get("issues")
        if not isinstance(raw_issues, list):
            return []
        out: list[str] = []
        for item in raw_issues[:max_issues]:
            as_str = str(item).strip()
            if as_str:
                out.append(as_str)
        return out


class BrandingComplianceRule(QualityRule):
    dimension = QualityDimension.BRANDING_COMPLIANCE
    applicable_output_types = {"pptx", "docx", "pdf", "xlsx"}

    _APPROVED_FILLS = {"dark", "mid_dark", "green", "dark_green", "gray", "mid", "white", "accent_light"}
    _FILLER_TITLE_WORDS = {
        "overview", "introduction", "background", "summary", "appendix",
        "agenda", "next steps", "takeaways", "context", "update",
    }

    def evaluate(self, output_type: str, text: str, metadata: dict[str, Any], context: dict[str, Any]) -> QualityResult:
        if output_type != "pptx":
            return QualityResult(score=1.0, issues=[], remediation_hint=None)

        raw = (text or "").strip()
        if not raw:
            return QualityResult(score=1.0, issues=[], remediation_hint=None)

        try:
            payload = json.loads(raw)
        except Exception:
            return QualityResult(score=1.0, issues=[], remediation_hint=None)

        slides = payload.get("slides") if isinstance(payload, dict) else payload
        if not isinstance(slides, list):
            return QualityResult(score=1.0, issues=[], remediation_hint=None)

        issues: list[str] = []
        fill_fields = (
            ("stat_cards", "fill"),
            ("column_cards", "accent"),
            ("stack_layers", "fill"),
            ("process_flow", "fill"),
        )

        for idx, slide in enumerate(slides, start=1):
            if not isinstance(slide, dict):
                continue
            slide_type = str(slide.get("slide_type") or "").lower()
            if slide_type in ("title", "section_divider"):
                continue

            # Check fill tokens are from the approved palette
            for list_field, token_field in fill_fields:
                items = slide.get(list_field)
                if not isinstance(items, list):
                    continue
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    fill = str(item.get(token_field) or "").strip().lower()
                    if fill and fill not in self._APPROVED_FILLS:
                        issues.append(
                            f"Slide {idx}: '{fill}' is not an approved brand fill token in {list_field}."
                        )

            # Flag topic-label titles (not insight assertions)
            title = str(slide.get("title") or "").strip().lower()
            if title and len(title.split()) <= 2 and title in self._FILLER_TITLE_WORDS:
                issues.append(
                    f"Slide {idx}: title '{slide.get('title')}' is a topic label, not an insight assertion."
                )

            # Flag missing eyebrow label on content slides with stat_cards or column_cards
            has_visual = any(isinstance(slide.get(k), list) and slide.get(k) for k in ("stat_cards", "column_cards"))
            subtitle = str(slide.get("subtitle") or "").strip()
            if has_visual and not subtitle:
                issues.append(
                    f"Slide {idx}: visual card slide is missing an eyebrow label (subtitle field)."
                )

        if not issues:
            return QualityResult(score=1.0, issues=[], remediation_hint=None)

        score = max(0.5, 1.0 - (0.1 * len(issues)))
        return QualityResult(
            score=score,
            issues=issues[:15],
            remediation_hint=(
                "Use only approved fill tokens (dark, mid_dark, green, dark_green, gray, mid). "
                "Replace topic-label titles with insight assertions. "
                "Add ALL-CAPS eyebrow labels to card slides."
            ),
        )


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
    def get(cls, kind: str) -> type[EvaluatorKind] | None:
        """Get an evaluator kind by name."""
        return cls._evaluators.get(str(kind).lower())

    @classmethod
    def all(cls) -> dict[str, type[EvaluatorKind]]:
        """Get all registered evaluator kinds."""
        return dict(cls._evaluators)


class ContractRuleFactory:
    """Factory to create QualityRule instances from JSON contract dimensions."""

    @staticmethod
    def create_rule_from_dimension(dimension_config: dict[str, Any]) -> QualityRule | None:
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

        dimension_config.get("id") or str(kind)
        float(dimension_config.get("weight", 0.33))
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
            StructuralCompletenessRule(),
            VisualQualityRule(),
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

        scores = [float(d["score"]) for d in dimensions.values()] if dimensions else [1.0]
        average = sum(scores) / len(scores)
        structural = dimensions.get(QualityDimension.STRUCTURAL_COMPLETENESS.value)
        structural_score = float(structural["score"]) if isinstance(structural, dict) else 1.0
        # Hard gate only for severe structural failure (e.g. invalid / empty PPTX slide bodies).
        if structural is not None and structural_score < 0.5:
            aggregate = min(average, structural_score)
        else:
            aggregate = average
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
