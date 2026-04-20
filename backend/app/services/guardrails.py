from __future__ import annotations

import re
from typing import Any

from app.services.claude import claude_generate_json, is_claude_enabled
from app.services.langfuse_tracing import langfuse_span
from app.services.observability import increment


class GuardrailPipeline:
    """
    Seven-gate guardrail pipeline.

    - Gates 1-6 are evaluated sequentially and stop at the first failure.
    - Gate 7 is evaluated only if gates 1-6 pass.
    - Gate 7 is the only hard block gate (quarantine).
    """

    _REFERENCE_PATTERNS = (
        re.compile(r"\[\d+\]"),  # [1], [2]
        re.compile(r"\(source:[^)]+\)", re.IGNORECASE),  # (source: ...)
        re.compile(r"https?://\S+", re.IGNORECASE),  # url refs
    )

    _PROMO_PATTERNS = (
        "best-in-class",
        "world-class",
        "unprecedented",
        "guaranteed",
        "revolutionary",
    )

    def _all_outputs_text(self, outputs: dict[str, str]) -> str:
        return "\n".join(v for v in outputs.values() if isinstance(v, str))

    def _contains_reference(self, text: str) -> bool:
        return any(p.search(text) for p in self._REFERENCE_PATTERNS)

    def _local_gate_eval(self, gate_key: str, outputs: dict[str, str]) -> tuple[str, str]:
        """Deterministic fallback checks for local mode."""
        text = self._all_outputs_text(outputs)
        lowered = text.lower()
        word_count = len(re.findall(r"\w+", text))

        if gate_key == "gate_1_source_grounding":
            if self._contains_reference(text):
                return "pass", "✓ Source grounding: Solid! References are clear."
            return "fail", "⚠️ Source grounding: No source references found. Add citations or source markers to ground claims."

        if gate_key == "gate_2_hallucination_check":
            claim_markers = ("according to", "research shows", "study found", "%", "percent")
            has_claim = any(marker in lowered for marker in claim_markers)
            if has_claim and not self._contains_reference(text):
                return "fail", "⚠️ Hallucination check: Claims made without supporting references. Back them up with sources."
            return "pass", "✓ Hallucination check: No unsupported claim patterns detected."

        if gate_key == "gate_3_brand_compliance":
            if any(phrase in lowered for phrase in self._PROMO_PATTERNS):
                return "fail", "⚠️ Brand tone: One phrase feels off-brand. Suggestion: Use consulting language instead of promotional tone."
            return "pass", "✓ Brand tone: Consulting-neutral and on-brand. Perfect!"

        if gate_key == "gate_4_reference_validation":
            if self._contains_reference(text):
                return "pass", "✓ Reference format: Citations are properly formatted."
            return "fail", "⚠️ Reference format: References needed but not present. Add [1], (source:...), or URLs."

        if gate_key == "gate_5_plagiarism_advisory":
            if word_count < 30:
                return "pass", "✓ Plagiarism check: Short output, low duplication risk."
            lines = [ln.strip().lower() for ln in text.splitlines() if ln.strip()]
            duplicated = len(lines) != len(set(lines))
            if duplicated:
                return "fail", "⚠️ Plagiarism advisory: Repeated lines detected. Ensure unique, original phrasing."
            return "pass", "✓ Plagiarism check: No repeated-line duplication signal. Looks original."

        if gate_key == "gate_6_style_enforcer":
            has_bullets = "- " in text or "* " in text
            has_heading = "# " in text or "## " in text
            has_long_sentence = any(len(s.split()) > 45 for s in re.split(r"[.!?]\s+", text) if s.strip())
            if (has_bullets or has_heading) and not has_long_sentence:
                return "pass", "✓ Readability: Structure and formatting are clear and scannable."
            return "fail", "⚠️ Readability: Add structure (headings, bullets) or break up long sentences for better clarity."

        return "fail", f"Unknown guardrail key: {gate_key}"

    def _eval_gate_with_claude(self, gate_key: str, outputs: dict[str, str]) -> str:
        system = "You are a strict compliance guardrail evaluator. Return strict JSON only."
        user = (
            f"Evaluate ONLY guardrail {gate_key} for the following consulting deliverables. "
            "Return JSON with keys: result (string 'pass' or 'fail') and brief_reason (string). "
            f"Deliverables:\n{outputs}"
        )
        res = claude_generate_json(system=system, user=user)
        if isinstance(res, dict):
            v = res.get("result")
            if isinstance(v, str) and v in ("pass", "fail"):
                return v
        return "fail"

    def evaluate(self, outputs: dict[str, str], dpdp_gate7: bool) -> dict[str, Any]:
        gate_order = [
            "gate_1_source_grounding",
            "gate_2_hallucination_check",
            "gate_3_brand_compliance",
            "gate_4_reference_validation",
            "gate_5_plagiarism_advisory",
            "gate_6_style_enforcer",
        ]

        gates: dict[str, str] = {}
        guardrail_events: list[dict[str, Any]] = []

        # Evaluate sequentially, stop at first fail.
        for gate_key in gate_order:
            if not is_claude_enabled():
                gate_result, reason = self._local_gate_eval(gate_key, outputs)
            else:
                try:
                    gate_result = self._eval_gate_with_claude(gate_key, outputs)
                    reason = "Evaluated by Claude."
                except Exception:  # noqa: BLE001 — safe fallback
                    gate_result = "fail"
                    reason = "Claude gate evaluation failed => conservative fail."

            gates[gate_key] = gate_result
            increment(f"guardrail_{gate_key}_{gate_result}_total")
            guardrail_events.append({"gate": gate_key, "result": gate_result, "reason": reason})

            if gate_result == "fail":
                langfuse_span(
                    trace_id=f"guardrails-{gate_key}",
                    name="guardrails.evaluate",
                    input_payload={"gate": gate_key, "outputs": list(outputs.keys())},
                    output_payload={"status": "fail"},
                )
                return {
                    "status": "fail",
                    "gates": {**gates, "gate_7_dpdp_compliance": "pending"},
                    "guardrail_events": guardrail_events,
                    "failed_gate": gate_key,
                    "retry_count": 0,
                }

        # Gate 1-6 all passed => evaluate gate 7.
        gate7_key = "gate_7_dpdp_compliance"
        gate7_result = "pass" if dpdp_gate7 else "fail"
        gates[gate7_key] = gate7_result
        increment(f"guardrail_{gate7_key}_{gate7_result}_total")
        guardrail_events.append(
            {
                "gate": gate7_key,
                "result": gate7_result,
                "reason": "DPDP gate 7 handled deterministically by DPDP redaction state.",
            }
        )

        status = "pass" if gate7_result == "pass" else "quarantined"
        langfuse_span(
            trace_id="guardrails-final",
            name="guardrails.evaluate",
            input_payload={"outputs": list(outputs.keys())},
            output_payload={"status": status},
        )
        return {
            "status": status,
            "gates": gates,
            "guardrail_events": guardrail_events,
            "failed_gate": None if status == "pass" else gate7_key,
            "retry_count": 0,
        }
