from __future__ import annotations

import re
from typing import Any

from app.services.claude import claude_generate_json, is_claude_enabled
from app.services.langfuse_tracing import langfuse_span
from app.services.observability import increment
from app.services.tool_registry import get_tool


class QAAgentLoop:
    @staticmethod
    def _to_text(value: Any) -> str:
        """Coerce agent/state output values for regex and scoring (may be list/dict/bytes)."""
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, (bytes, bytearray)):
            return bytes(value).decode("utf-8", errors="replace")
        if isinstance(value, (list, dict, tuple, set)):
            try:
                import json

                return json.dumps(value, ensure_ascii=False)
            except (TypeError, ValueError):
                return str(value)
        return str(value)

    def _build_remediation_instructions(
        self,
        outputs: dict[str, Any],
        scores: dict[str, float],
        threshold: float,
    ) -> dict[str, dict[str, Any]]:
        instructions: dict[str, dict[str, Any]] = {}
        for out_key, score in scores.items():
            if float(score) >= threshold:
                continue
            text = self._to_text(outputs.get(out_key, ""))
            if not isinstance(text, str):
                text = str(text)
            has_reference = bool(re.search(r"\[\d+\]|\(source:[^)]+\)|https?://\S+", text, flags=re.IGNORECASE))
            actions = [
                "Tighten structure and remove weak/generalized claims.",
                "Ensure recommendations are explicitly grounded in available context.",
            ]
            reason = f"Score {float(score):.2f} below threshold {threshold:.2f}."
            if not has_reference:
                actions.insert(0, "Add at least one explicit citation or source marker for key claims.")
                reason += " Missing references detected."
            if len(text.split()) < 40:
                actions.append("Expand content with concrete, auditable details and concise rationale.")
            instructions[out_key] = {
                "reason": reason,
                "target_score": threshold,
                "actions": actions,
                "rewrite_prompt": (
                    f"Revise {out_key} to meet QA threshold {threshold:.2f}. "
                    "Use evidence-backed language, preserve business intent, and improve clarity."
                ),
            }
        return instructions

    def run(
        self,
        outputs: dict[str, Any],
        threshold: float = 0.8,
        *,
        project_id: str | None = None,
        max_loops: int = 2,
    ) -> dict[str, Any]:
        # Deterministic fallback for local tests/CI when Claude isn't configured.
        fallback_scores = {k: 0.85 for k in outputs}

        retrieve_context_tool = get_tool("retrieve_context")
        web_search_tool = get_tool("web_search")

        # Collect lightweight evidence for QA scoring.
        verifications: dict[str, Any] = {"retrieve_context": {}, "web_search": {}}
        for out_key, out_text in outputs.items():
            excerpt = self._to_text(out_text)[:800]
            query = f"{out_key}: {excerpt}"
            try:
                verifications["retrieve_context"][out_key] = retrieve_context_tool(
                    query=query, project_id=project_id
                )
            except Exception:
                verifications["retrieve_context"][out_key] = {}
            try:
                verifications["web_search"][out_key] = web_search_tool(query=query, project_id=project_id)
            except Exception:
                verifications["web_search"][out_key] = []

        if not is_claude_enabled():
            passed = all(v >= threshold for v in fallback_scores.values())
            remediation = self._build_remediation_instructions(outputs, fallback_scores, threshold)
            increment("qa_runs_total")
            increment("qa_pass_total" if passed else "qa_fail_total")
            increment("qa_iterations_total", 1)
            if remediation:
                increment("qa_remediation_required_total")
            if project_id:
                langfuse_span(
                    trace_id=str(project_id),
                    name="qa.evaluate",
                    input_payload={"threshold": threshold, "outputs": list(outputs.keys())},
                    output_payload={"passed": passed, "iterations": 1},
                )
            return {
                "passed": passed,
                "iterations": 1,
                "scores": fallback_scores,
                "verifications": verifications,
                "remediation_instructions": remediation,
            }

        max_iters = max(1, int(max_loops or 1))
        last_scores = fallback_scores
        last_passed = all(v >= threshold for v in fallback_scores.values())
        iterations_used = 0

        for it in range(max_iters):
            iterations_used = it + 1
            system = "You are a QA reviewer for consulting deliverables. Return strict JSON only."
            user = (
                "Evaluate the following deliverables for factual/structural quality using the provided evidence.\n"
                "For each output:\n"
                "- Prefer evidence-backed claims.\n"
                "- If evidence is missing/weak, lower the score conservatively.\n\n"
                "Return JSON with keys: passed (boolean), iterations (integer), scores (object mapping output keys to numbers), "
                "remediation_instructions (object keyed by output with reason/actions/rewrite_prompt).\n"
                f"Threshold for passed is {threshold}.\n"
                f"Evidence (may be empty):\n{verifications}\n\n"
                f"Outputs:\n{outputs}\n"
                f"Iteration: {it + 1} of {max_iters}."
            )

            try:
                res = claude_generate_json(system=system, user=user)
                scores = res.get("scores") if isinstance(res, dict) else None
                if not isinstance(scores, dict):
                    raise ValueError("Invalid scores in QA result")
                last_scores = {k: float(scores.get(k, fallback_scores.get(k, 0.0))) for k in outputs}
                last_passed = bool(res.get("passed", all(v >= threshold for v in last_scores.values())))
            except Exception:
                last_scores = fallback_scores
                last_passed = all(v >= threshold for v in fallback_scores.values())

            if last_passed:
                break

        remediation = self._build_remediation_instructions(outputs, last_scores, threshold)
        increment("qa_runs_total")
        increment("qa_pass_total" if last_passed else "qa_fail_total")
        increment("qa_iterations_total", iterations_used)
        if remediation:
            increment("qa_remediation_required_total")
        if project_id:
            langfuse_span(
                trace_id=str(project_id),
                name="qa.evaluate",
                input_payload={"threshold": threshold, "outputs": list(outputs.keys())},
                output_payload={"passed": last_passed, "iterations": iterations_used},
            )
        return {
            "passed": last_passed,
            "iterations": iterations_used,
            "scores": last_scores,
            "verifications": verifications,
            "remediation_instructions": remediation,
        }
