"""Concrete implementations of EvaluatorKind for quality assessment."""

from __future__ import annotations

import logging
import re
from typing import Any

from app.core.quality_framework import EvaluatorKind

logger = logging.getLogger(__name__)


class SectionCoverageEvaluator(EvaluatorKind):
    """Evaluate whether required sections are present in deliverable content."""

    def evaluate(
        self,
        text: str,
        dimension_config: dict[str, Any],
    ) -> tuple[float, dict[str, Any]]:
        """Check for required sections in markdown/text content.

        Args:
            text: Text or markdown content to evaluate
            dimension_config: Dict with 'required_sections' list, 'weight_per_section' float

        Returns:
            (score: 0-1, metadata: dict with coverage details)
        """
        required_sections = dimension_config.get("required_sections", [])
        if not required_sections:
            return (1.0, {"message": "No required sections configured"})

        text_lower = (text or "").lower()
        found_sections = []
        missing_sections = []

        for section in required_sections:
            section_lower = str(section).lower()
            # Check for heading-like patterns: "## Section Name" or "### Section Name"
            patterns = [
                rf"^#+\s*{re.escape(section_lower)}\s*$",
                rf"^{re.escape(section_lower)}\s*$",
                rf"^{re.escape(section_lower)}\:",
            ]
            found = any(re.search(pattern, text_lower, re.MULTILINE) for pattern in patterns)
            if found:
                found_sections.append(section)
            else:
                missing_sections.append(section)

        # Calculate score: 1.0 if all sections found, proportional otherwise
        coverage_ratio = len(found_sections) / len(required_sections) if required_sections else 0
        score = coverage_ratio

        return (
            score,
            {
                "total_required": len(required_sections),
                "found": len(found_sections),
                "missing": missing_sections,
                "coverage_ratio": coverage_ratio,
            },
        )


class CitationDensityEvaluator(EvaluatorKind):
    """Evaluate citation/reference density in content."""

    def evaluate(
        self,
        text: str,
        dimension_config: dict[str, Any],
    ) -> tuple[float, dict[str, Any]]:
        """Count citation markers and check density against minimum threshold.

        Args:
            text: Text content with potential citations
            dimension_config: Dict with 'min_citation_density' (citations per 100 words), 'citation_marker' pattern

        Returns:
            (score: 0-1, metadata: dict with citation details)
        """
        text = text or ""
        min_density = float(dimension_config.get("min_citation_density", 0.5))
        citation_marker = dimension_config.get("citation_marker", r"\[[\d\w]+\]")

        # Count citations
        citations = re.findall(citation_marker, text)
        citation_count = len(citations)

        # Count words
        words = text.split()
        word_count = len(words)

        if word_count == 0:
            return (0.5, {"citations": 0, "words": 0, "density": 0, "min_density": min_density})

        # Calculate density: citations per 100 words
        density = (citation_count / word_count) * 100

        # Score: reached target density = 1.0, 0 density = 0.0
        score = min(1.0, density / min_density) if min_density > 0 else 1.0

        return (
            score,
            {
                "citations": citation_count,
                "words": word_count,
                "density": round(density, 2),
                "min_density": min_density,
                "sufficient": density >= min_density,
            },
        )


class LLMCritiqueEvaluator(EvaluatorKind):
    """Use Claude to evaluate deliverable against a rubric."""

    def evaluate(
        self,
        text: str,
        dimension_config: dict[str, Any],
    ) -> tuple[float, dict[str, Any]]:
        """Evaluate text using Claude API against a rubric.

        Args:
            text: Text to evaluate
            dimension_config: Dict with 'rubric' (evaluation criteria), 'dimensions' list

        Returns:
            (score: 0-1, metadata: dict with critique details)
        """
        # For now, return a placeholder score
        # In full implementation, this would call Claude API
        rubric = dimension_config.get("rubric", "Evaluate overall quality")
        dimensions = dimension_config.get("dimensions", ["clarity", "completeness"])

        logger.warning(
            "LLMCritiqueEvaluator: Claude API call not yet implemented. "
            "Returning placeholder score. Rubric: %s",
            rubric,
        )

        # Placeholder: rate based on text length as proxy for completeness
        text_len = len((text or "").strip())
        score = min(1.0, text_len / 500)  # Score increases with content length up to 500 chars

        return (
            score,
            {
                "rubric": rubric,
                "dimensions": dimensions,
                "text_length": text_len,
                "placeholder_score": True,
                "message": "LLMCritiqueEvaluator: Claude API not yet implemented",
            },
        )


class ContentLengthEvaluator(EvaluatorKind):
    """Evaluate content by minimum length requirement."""

    def evaluate(
        self,
        text: str,
        dimension_config: dict[str, Any],
    ) -> tuple[float, dict[str, Any]]:
        """Check that content meets minimum length threshold.

        Args:
            text: Text content to evaluate
            dimension_config: Dict with 'min_characters' (minimum content length)

        Returns:
            (score: 0-1, metadata: dict with length details)
        """
        min_chars = int(dimension_config.get("min_characters", 80))
        text_stripped = (text or "").strip()
        text_len = len(text_stripped)

        # Score: 1.0 if above minimum, proportional otherwise
        score = min(1.0, text_len / min_chars) if min_chars > 0 else 1.0

        return (
            score,
            {
                "text_length": text_len,
                "min_required": min_chars,
                "sufficient": text_len >= min_chars,
            },
        )


class CompletenessEvaluator(EvaluatorKind):
    """Evaluate completeness of deliverable structure."""

    def evaluate(
        self,
        text: str,
        dimension_config: dict[str, Any],
    ) -> tuple[float, dict[str, Any]]:
        """Check structure completeness (headings, sections, non-empty content).

        Args:
            text: Markdown or structured text to evaluate
            dimension_config: Dict with 'min_non_empty_sections' (minimum filled sections)

        Returns:
            (score: 0-1, metadata: dict with completeness details)
        """
        text = text or ""
        min_sections = int(dimension_config.get("min_non_empty_sections", 3))

        # Count non-empty sections (separated by headings or blank lines)
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
        non_empty_count = len(lines)

        # Score based on whether we have enough content
        score = min(1.0, non_empty_count / (min_sections * 3)) if min_sections > 0 else 1.0

        return (
            score,
            {
                "non_empty_lines": non_empty_count,
                "min_sections": min_sections,
                "sufficient": non_empty_count >= (min_sections * 3),
            },
        )
