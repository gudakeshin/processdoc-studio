import json
import logging
import re
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from app.agents.agent_types import AgentOutput, build_agent_context, merge_agent_output, validate_agent_output
from app.agents.coordinator_teammate_integration import CoordinatorTeammateIntegration
from app.agents.subagents import (
    run_docx_agent,
    run_drawio_agent,
    run_narrative_agent,
    run_pdf_agent,
    run_pptx_agent,
    run_process_extraction,  # noqa: F401 — used via _coordinator_module in coordinator_execution.py
    run_sop_agent,
    run_xlsx_agent,
)
from app.core.config import settings
from app.core.deliverable import DeliverableRegistry
from app.core.quality_framework import UnifiedQualityFramework
from app.core.state import ProcessDocState
from app.db.session import SessionLocal
from app.services.branding_service import BrandingService
from app.services.claude import (  # noqa: F401 — used via _coordinator_module in coordinator_planning.py
    claude_generate_with_thinking,
    is_claude_enabled,
)
from app.services.content_enrichment import ContentEnrichmentEngine
from app.services.dpdp import DPDPService
from app.services.guardrails import GuardrailPipeline
from app.services.hooks import run_hooks_sync  # noqa: F401 — used via _coordinator_module in coordinator_execution.py
from app.services.observability import increment
from app.services.otel_tracing import start_span
from app.services.proposal_policy import derive_proposal_skill_targets
from app.services.qa import QAAgentLoop
from app.services.retrieval import TieredContextEngine
from app.services.teammate_executor import TeammateExecutor

_OUTPUT_AGENTS: dict[str, object] = {
    "process_map": run_drawio_agent,
    "docx":        run_docx_agent,
    "pptx":        run_pptx_agent,
    "xlsx":        run_xlsx_agent,
    "pdf":         run_pdf_agent,
    "sop":         run_sop_agent,
    "narrative":   run_narrative_agent,
}

# Rough complexity weights (1=fast, 5=slow) for ordering metadata emitted in coordinator_plan events.
# Does not change execution order (which is LLM-driven); used as a scheduling hint.
_OUTPUT_TYPE_COMPLEXITY: dict[str, int] = {
    "pptx": 5, "xlsx": 4, "docx": 3, "pdf": 3,
    "narrative": 2, "sop": 2, "process_map": 1,
}

_OUTPUT_TYPE_REQUIREMENTS_PATH = Path(__file__).resolve().parents[2] / "config" / "output_types.json"
_JSON_PATH_CACHE: dict[str, tuple[int, object]] = {}

_EVENT_COORDINATOR_PLAN = "coordinator_plan"
_MAX_EVENT_TEXT = 4000
_DEBUG_LOG_PATH = Path(settings.processdoc_coordinator_debug_log).expanduser() if str(settings.processdoc_coordinator_debug_log or "").strip() else None
_DEBUG_SESSION_ID = "a9841a"
_LOG = logging.getLogger(__name__)

def _session_debug_log(*, run_id: str | None, hypothesis_id: str, location: str, message: str, data: dict[str, Any]) -> None:
    if _DEBUG_LOG_PATH is None:
        return
    try:
        payload = {
            "sessionId": _DEBUG_SESSION_ID,
            "runId": str(run_id or ""),
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data,
            "timestamp": int(time.time() * 1000),
        }
        _DEBUG_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _DEBUG_LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=True) + "\n")
    except Exception as exc:
        _LOG.debug("coordinator session debug log write failed: %s", exc)


@dataclass
class ExecutionPlan:
    """LLM or fallback ordering for output agents; merged against user-requested ceiling."""

    ordered_output_types: list[str]
    rationale: str
    per_output_notes: dict[str, str] = field(default_factory=dict)
    used_llm_plan: bool = False
    fallback_reason: str | None = None
    thinking_excerpt: str = ""
    execution_milestones: list[dict[str, Any]] = field(default_factory=list)


def _milestone_labels_from_plan(plan: ExecutionPlan, wanted: list[str]) -> dict[str, str]:
    labels: dict[str, str] = {}
    want = {str(x).strip() for x in wanted if str(x).strip()}
    for m in plan.execution_milestones:
        if not isinstance(m, dict):
            continue
        ot = str(m.get("output_type") or "").strip()
        label = str(m.get("label") or "").strip()
        if ot in want and label:
            labels[f"out:{ot}"] = label
    return labels


def _load_json_path_cached(path: Path) -> object:
    cache_key = str(path)
    stat = path.stat()
    cached = _JSON_PATH_CACHE.get(cache_key)
    if cached and cached[0] == stat.st_mtime_ns:
        return cached[1]
    raw = path.read_text(encoding="utf-8")
    parsed = json.loads(raw)
    _JSON_PATH_CACHE[cache_key] = (stat.st_mtime_ns, parsed)
    return parsed


def _debug_log(hypothesis_id: str, location: str, message: str, data: dict) -> None:
    raw = (settings.processdoc_coordinator_debug_log or "").strip()
    if not raw:
        return
    path = Path(raw)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "sessionId": "5b96f3",
            "runId": "skill-selection-check",
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data,
            "timestamp": int(time.time() * 1000),
        }
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=True) + "\n")
    except Exception as exc:
        _LOG.debug("coordinator debug log write failed: %s", exc)


# Deliverable types that map to a format type + content skill hint.
# When a user requests "sop", they mean a docx document driven by sop_v2 content skill.
_DELIVERABLE_TO_FORMAT: dict[str, tuple[str, str]] = {
    "sop": ("docx", "sop_v2"),
    "raci": ("xlsx", "raci_v2"),
    "narrative": ("docx", "narrative_v2"),
    "report": ("pdf", "narrative_v2"),
    "approach_note": ("docx", "approach_note_v1"),
    "brd": ("docx", "brd_v1"),
    "proposal": ("docx", "proposal_finance_transformation_v1"),
    "deck": ("pptx", "narrative_v2"),
    "executive_deck": ("pptx", "narrative_v2"),
    "brd_deck": ("pptx", "brd_v1"),
    "proposal_deck": ("pptx", "proposal_finance_transformation_v1"),
}

# Format-type aliases (file format synonyms only — no deliverable types)
_FORMAT_ALIASES: dict[str, str] = {
    "process_map": "process_map",
    "drawio": "process_map",
    "diagram": "process_map",
    "map": "process_map",
    "docx": "docx",
    "word": "docx",
    "pptx": "pptx",
    "ppt": "pptx",
    "presentation": "pptx",
    "slides": "pptx",
    "xlsx": "xlsx",
    "excel": "xlsx",
    "spreadsheet": "xlsx",
    "pdf": "pdf",
}


def _canonical_requested(raw: list[str] | None) -> tuple[list[str], dict[str, str]]:
    """
    Canonicalise requested output types to format types only.

    Returns:
        (output_types, content_skill_hints)
        where content_skill_hints[format_type] = skill_id to use as primary content skill.

    Deliverable aliases (sop, raci, narrative) are mapped to their format type
    and generate a content skill hint that the coordinator injects as the primary
    skill for that output's generation. The skill drives what content structure
    the format agent produces (SOP sections, RACI table, executive briefing, etc.).
    """
    out: list[str] = []
    hints: dict[str, str] = {}
    for x in raw or []:
        token = (x or "").strip().lower()
        if token in _DELIVERABLE_TO_FORMAT:
            fmt, skill_hint = _DELIVERABLE_TO_FORMAT[token]
            if fmt not in out:
                out.append(fmt)
            hints.setdefault(fmt, skill_hint)  # first hint wins per format type
        elif token in _FORMAT_ALIASES:
            key = _FORMAT_ALIASES[token]
            if key not in out:
                out.append(key)
        elif token:
            if token not in out:
                out.append(token)
    if out:
        return out, hints
    # No implicit default output types; caller must provide explicit selection.
    return [], hints


def _merge_intent_hints(
    *,
    wanted: list[str],
    existing_hints: dict[str, str],
    instruction: str,
) -> dict[str, str]:
    """
    Add content-skill hints when callers requested only format types (docx/pptx/pdf)
    but user intent clearly implies a deliverable-specific skill.
    """
    hints = dict(existing_hints or {})
    text = (instruction or "").strip().lower()
    if not text:
        return hints

    # Generic alias recovery: infer deliverable aliases from instruction text.
    for token, (fmt, skill_hint) in _DELIVERABLE_TO_FORMAT.items():
        if fmt not in wanted or fmt in hints:
            continue
        aliases = {token, token.replace("_", " ")}
        if any(a and a in text for a in aliases):
            hints[fmt] = skill_hint

    proposal_targets = derive_proposal_skill_targets(
        instruction=text,
        output_types=wanted,
        base_targets=hints,
    )
    hints.update(proposal_targets)

    return hints


def _sanitize_content_skill_targets(raw: object) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in raw.items():
        ks = str(k or "").strip()
        vs = str(v or "").strip()
        if ks and vs:
            out[ks] = vs
    return out


def _skill_public_dict(card: dict | None) -> dict:
    if not isinstance(card, dict):
        return {}
    return {k: v for k, v in card.items() if not str(k).startswith("_")}


def _merge_planned_output_order(planned: list[str], ceiling: list[str]) -> list[str]:
    """Preserve planner order for valid types, then append any remaining ceiling types."""
    ceiling_set = set(ceiling)
    seen: set[str] = set()
    out: list[str] = []
    for t in planned:
        if t in ceiling_set and t not in seen:
            out.append(t)
            seen.add(t)
    for t in ceiling:
        if t not in seen:
            out.append(t)
    return out


def _trim_registry_for_planning(registry: list[dict]) -> list[dict]:
    """
    Build a compact skill summary for the coordinator planning prompt.
    Includes ``use_when`` so the LLM can make intent-driven skill decisions,
    and ``role`` so it knows which skills are post-processors vs. primary generators.
    """
    out: list[dict] = []
    for card in registry:
        if not isinstance(card, dict):
            continue
        entry: dict = {
            "id": str(card.get("id") or "").strip(),
            "output_types": list(card.get("output_types") or []),
            "display_name": str(card.get("display_name") or card.get("title") or card.get("name") or "")[:80],
            "role": str(card.get("role") or "primary").strip().lower(),
        }
        use_when = str(card.get("use_when") or card.get("description") or "").strip()
        if use_when:
            entry["use_when"] = use_when[:200]
        out.append(entry)
    return out


def _process_model_summary(state: ProcessDocState) -> str:
    pm = state.get("process_model")
    if not isinstance(pm, dict):
        return "{}"
    raw = json.dumps(pm, ensure_ascii=True)
    if len(raw) > 12000:
        return raw[:12000] + "\n…"
    return raw


def _truncate_event_text(text: str, limit: int = _MAX_EVENT_TEXT) -> str:
    t = (text or "").strip()
    if len(t) <= limit:
        return t
    return t[: limit - 1] + "…"



from app.agents.coordinator_execution import CoordinatorExecution
from app.agents.coordinator_planning import CoordinatorPlanning


class Coordinator(CoordinatorExecution, CoordinatorPlanning):
    def __init__(self) -> None:
        self.context_engine = TieredContextEngine()
        self.qa_loop = QAAgentLoop()
        self.guardrails = GuardrailPipeline()
        self.dpdp = DPDPService()
        self.enrichment_engine = ContentEnrichmentEngine()
        self.quality_framework = UnifiedQualityFramework()
        self.skill_registry = self._load_skill_registry()
        self.output_requirements = self._load_output_requirements()

        # Phase 2: Initialize subprocess executor for independent teammate processes
        use_subprocess = bool(getattr(settings, "coordinator_use_subprocess_workers", False))
        if use_subprocess:
            self.executor = TeammateExecutor(max_processes=8)
            self.teammate_integration: CoordinatorTeammateIntegration | None = None
            _LOG.warning(
                "coordinator_use_subprocess_workers=True but TeammateExecutor is only active "
                "in the deprecated run() path — _run_event_loop ignores self.executor. "
                "Set coordinator_use_subprocess_workers=False to suppress this warning."
            )
        else:
            self.executor = None
            self.teammate_integration = None

    @staticmethod
    def _load_skill_registry() -> list[dict]:
        from app.services.skill_document import load_builtin_skills

        return load_builtin_skills()

    @staticmethod
    def _load_output_requirements() -> dict[str, list[str]]:
        try:
            parsed = _load_json_path_cached(_OUTPUT_TYPE_REQUIREMENTS_PATH)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return {}
        out: dict[str, list[str]] = {}
        if isinstance(parsed, list):
            for item in parsed:
                if not isinstance(item, dict):
                    continue
                fid = str(item.get("output_type_id") or "").strip()
                req = item.get("required_skills")
                if fid and isinstance(req, list):
                    out[fid] = [str(x).strip() for x in req if str(x).strip()]
        return out

    def _parallel_read_stages(self, state: ProcessDocState) -> dict[str, Any]:
        """AD-02 explicit read-only fanout with fail-fast errors."""
        started = time.perf_counter()

        def context_assembly() -> dict[str, Any]:
            t0 = time.perf_counter()
            out = {"context_ready": bool(str(state.get("raw_text") or "").strip())}
            return {"context_bundle": out, "duration_ms": int((time.perf_counter() - t0) * 1000.0)}

        def skill_selection() -> dict[str, Any]:
            t0 = time.perf_counter()
            requested = state.get("requested_outputs") if isinstance(state.get("requested_outputs"), list) else []
            out = {"requested_outputs_count": len(requested)}
            return {"skill_selection_result": out, "duration_ms": int((time.perf_counter() - t0) * 1000.0)}

        def plan_validation() -> dict[str, Any]:
            t0 = time.perf_counter()
            pp = state.get("plan_payload")
            out = {"plan_payload_valid": isinstance(pp, dict) or pp is None}
            return {"plan_validation_result": out, "duration_ms": int((time.perf_counter() - t0) * 1000.0)}

        funcs = [context_assembly, skill_selection, plan_validation]
        results: list[Any] = []
        with ThreadPoolExecutor(max_workers=3) as ex:
            futures = [ex.submit(fn) for fn in funcs]
            for fut in futures:
                try:
                    results.append(fut.result())
                except Exception as exc:  # noqa: BLE001
                    results.append(exc)
        names = ["context_assembly", "skill_selection", "plan_validation"]
        out: dict[str, Any] = {}
        errors: list[dict[str, str]] = []
        for idx, res in enumerate(results):
            name = names[idx]
            if isinstance(res, Exception):
                errors.append({"stage": name, "error": str(res)})
            elif isinstance(res, dict):
                out[name] = res
        if errors:
            out["errors"] = errors
        out["fanout_duration_ms"] = int((time.perf_counter() - started) * 1000.0)
        return out

    @staticmethod
    def _load_project_custom_skills(project_id: str | None) -> list[dict]:
        if not project_id:
            return []
        try:
            from app.services.skill_document import load_custom_skills_from_workspace
            from app.services.storage import workspace_path

            base = workspace_path(project_id) / "custom_skills"
            return load_custom_skills_from_workspace(base)
        except (OSError, ValueError, TypeError, ImportError):
            return []

    @staticmethod
    def _state_key_for_output(output_key: str) -> str | None:
        mapping = {
            "docx_markdown": "docx_markdown",
            "xlsx_markdown": "xlsx_markdown",
            "pdf_markdown": "pdf_markdown",
            "drawio_xml": "drawio_xml",
            "pptx_slides": "pptx_slides",
            "sop_markdown": "sop_markdown",
            "narrative_md": "narrative_md",
        }
        return mapping.get(output_key)

    def _apply_qa_remediation(
        self,
        state: ProcessDocState,
        wanted: list[str],
        remediation_instructions: dict[str, Any],
    ) -> dict[str, str]:
        # Map from output state key → output_type_id used in _OUTPUT_AGENTS.
        # Agents are resolved dynamically at call time so monkeypatching _OUTPUT_AGENTS works.
        _STATE_KEY_TO_OUTPUT_TYPE: dict[str, str] = {
            "docx_markdown": "docx",
            "xlsx_markdown": "xlsx",
            "pdf_markdown": "pdf",
            "drawio_xml": "process_map",
            "pptx_slides": "pptx",
            "sop_markdown": "sop",
            "narrative_md": "narrative",
        }
        remediation_texts: list[str] = []
        rerun_agent_keys: list[str] = []
        for out_key, instruction in remediation_instructions.items():
            output_type = _STATE_KEY_TO_OUTPUT_TYPE.get(out_key)
            if output_type is None:
                continue
            if output_type not in _OUTPUT_AGENTS:
                continue
            if output_type not in wanted:
                continue
            actions = instruction.get("actions") if isinstance(instruction, dict) else []
            action_lines = [str(a).strip() for a in actions if str(a).strip()]
            if action_lines:
                remediation_texts.append(f"{out_key}: " + " | ".join(action_lines))
            rerun_agent_keys.append(out_key)

        if remediation_texts:
            state["qa_remediation_notes"] = "\n".join(remediation_texts)
            # Quality remediation flows only through assembled_context (sentinel-wrapped)
            # so user_instruction/raw_text stay clean for process extraction.
            ac = str(state.get("assembled_context") or "")

            from app.services.agent_personality import format_remediation_with_personality
            from app.services.qa_remediation_channel import wrap_qa_feedback

            action_items = remediation_texts
            feedback_block = wrap_qa_feedback(
                format_remediation_with_personality(
                    issues=[],
                    action_items=action_items,
                )
            )

            if ac.strip():
                state["assembled_context"] = (feedback_block + "\n\n" + ac)[:12000]
            else:
                state["assembled_context"] = feedback_block[:12000]

        for out_key in rerun_agent_keys:
            output_type = _STATE_KEY_TO_OUTPUT_TYPE.get(out_key)
            if not output_type:
                continue
            fn = _OUTPUT_AGENTS.get(output_type)
            if not fn:
                continue

            # ── PPTX targeted repair: use existing repair mode infrastructure ──
            # Instead of regenerating all slides from scratch, inject prior slides
            # and remediation actions as visual_feedback so the agent only fixes
            # the slides that failed QA (same mechanism as Visual QA repair).
            if out_key == "pptx_slides" and state.get("pptx_slides") is not None:
                prior_slides = state.get("pptx_slides")
                # Parse prior slides if stored as string
                if isinstance(prior_slides, str):
                    try:
                        parsed = json.loads(prior_slides)
                        if isinstance(parsed, dict) and isinstance(parsed.get("slides"), list):
                            prior_slides = parsed["slides"]
                        elif isinstance(parsed, list):
                            prior_slides = parsed
                    except (json.JSONDecodeError, TypeError):
                        prior_slides = None

                instruction = remediation_instructions.get(out_key, {})
                actions = instruction.get("actions", []) if isinstance(instruction, dict) else []

                if isinstance(prior_slides, list) and prior_slides and actions:
                    # Build visual feedback entries targeting slides with issues
                    visual_feedback: list[dict] = []
                    for action_text in actions:
                        action_str = str(action_text).strip()
                        if not action_str:
                            continue
                        # Try to extract slide index from action text (e.g., "Slide 3 (...)")
                        slide_match = re.search(r"Slide\s+(\d+)", action_str, re.IGNORECASE)
                        if slide_match:
                            visual_feedback.append({
                                "slide_index": int(slide_match.group(1)),
                                "instruction": action_str,
                            })
                        else:
                            # Section-level action: target all slides as candidates
                            # The agent will determine which slides need updates
                            visual_feedback.append({
                                "slide_index": 0,  # 0 = global instruction
                                "instruction": action_str,
                            })

                    # Inject into plan_payload so the PPTX agent enters repair mode
                    pp = state.get("plan_payload")
                    if not isinstance(pp, dict):
                        pp = {}
                        state["plan_payload"] = pp
                    pp["prior_pptx_slides"] = prior_slides
                    pp["pptx_visual_feedback"] = visual_feedback

            ctx = build_agent_context(state, output_type)
            merge_agent_output(state, fn(ctx))  # type: ignore[arg-type]

        refreshed: dict[str, str] = {}
        for state_key in ("docx_markdown", "xlsx_markdown", "pdf_markdown", "drawio_xml", "pptx_slides"):
            if state.get(state_key) is not None:
                refreshed[state_key] = state.get(state_key, "")
        return refreshed

    @staticmethod
    def _outputs_from_state(state: ProcessDocState, wanted: list[str]) -> dict[str, str]:
        outputs: dict[str, str] = {}
        if "docx" in wanted:
            outputs["docx_markdown"] = state.get("docx_markdown", "")
        if "xlsx" in wanted:
            outputs["xlsx_markdown"] = state.get("xlsx_markdown", "")
        if "pdf" in wanted:
            outputs["pdf_markdown"] = state.get("pdf_markdown", "")
        if "process_map" in wanted:
            outputs["drawio_xml"] = state.get("drawio_xml", "")
        if "pptx" in wanted and state.get("pptx_slides"):
            import json as _json
            outputs["pptx_slides"] = _json.dumps(state.get("pptx_slides") or [])
        return outputs

    def _ensure_deliverable_archetype(self, state: ProcessDocState) -> None:
        if not settings.deliverable_archetype_enabled:
            return
        if state.get("deliverable_archetype"):
            return
        instruction = str(
            state.get("user_intent_original")
            or state.get("user_instruction")
            or state.get("raw_text")
            or ""
        )
        plan_payload = state.get("plan_payload") if isinstance(state.get("plan_payload"), dict) else None
        skill_card = state.get("skill_card") if isinstance(state.get("skill_card"), dict) else None
        from app.services.deliverable_archetype import detect_deliverable_archetype

        state["deliverable_archetype"] = detect_deliverable_archetype(
            instruction,
            plan_payload=plan_payload,
            skill_card=skill_card,
        )

    def _initialize_framework_context(self, state: ProcessDocState, wanted: list[str]) -> None:
        # Branding must reach the renderers regardless of the framework flags;
        # without it each renderer falls back to a different default company name.
        db = SessionLocal()
        try:
            branding = BrandingService(db).get_branding_for_run(
                project_id=state.get("project_id"),
                skill_card=state.get("skill_card") if isinstance(state.get("skill_card"), dict) else None,
                run_config=state.get("run_config") if isinstance(state.get("run_config"), dict) else None,
            )
            state["branding_context"] = branding
        finally:
            db.close()
        if not (
            settings.enable_deliverable_registry
            or settings.enable_content_enrichment_engine
            or settings.enable_unified_quality_framework
        ):
            return
        if settings.enable_content_enrichment_engine:
            enrichment = self.enrichment_engine.enrich(
                user_instruction=str(state.get("user_instruction") or ""),
                process_model=state.get("process_model") if isinstance(state.get("process_model"), dict) else {},
                prior_artifacts={
                    "narrative": state.get("narrative_md"),
                    "docx": state.get("docx_markdown"),
                    "pdf": state.get("pdf_markdown"),
                },
            )
            state["content_enrichment"] = enrichment
        if settings.enable_deliverable_registry:
            by_output: dict[str, Any] = {}
            for output_type in wanted:
                try:
                    by_output[output_type] = DeliverableRegistry.get(output_type).get_metadata()
                except Exception:  # noqa: S112 — best-effort, non-fatal
                    continue
            state["deliverable_metadata_by_output_type"] = by_output

    def _run_unified_quality_framework(
        self,
        state: ProcessDocState,
        outputs: dict[str, str],
        wanted: list[str],
        *,
        apply_remediation: bool = True,
        emit_event: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        if not settings.enable_unified_quality_framework:
            return {}, outputs
        reports: dict[str, Any] = {}
        key_map = {
            "docx_markdown": "docx",
            "xlsx_markdown": "xlsx",
            "pdf_markdown": "pdf",
            "pptx_slides": "pptx",
        }
        for output_key, text in outputs.items():
            output_type = key_map.get(output_key)
            if not output_type or output_type not in wanted:
                continue
            metadata: dict[str, Any] = {}
            try:
                from app.services.storage import workspace_path

                project_id = str(state.get("project_id") or "").strip()
                run_id = str(state.get("run_id") or "").strip()
                if project_id and run_id:
                    run_dir = workspace_path(project_id) / "runs" / run_id
                    deliverable = DeliverableRegistry.get(output_type)
                    meta = deliverable.get_metadata()
                    artifact_name = "drawio.xml" if output_type == "process_map" else f"output{meta.file_extension}"
                    artifact_path = run_dir / artifact_name
                    if artifact_path.exists():
                        metadata = deliverable.extract_quality_signals(artifact_path)
                        if emit_event and metadata.get("content_pending_slides", 0) > 0:
                            emit_event("step", {
                                "status": "post_processing_start",
                                "agent": output_type,
                                "step": f"quality_check_{output_type}",
                                "message": (
                                    f"{metadata['content_pending_slides']} slide(s) rendered as "
                                    "'Content pending' — payload was missing or invalid. "
                                    "Use the regenerate-slide action to fix individual slides."
                                ),
                                "content_pending_slides": metadata["content_pending_slides"],
                                "slide_count": metadata.get("slide_count", 0),
                            })
            except Exception:
                metadata = {}
            reports[output_type] = self.quality_framework.evaluate_deliverable(
                output_type=output_type,
                text=str(text or ""),
                metadata=metadata,
                context={"branding": state.get("branding_context"), "enrichment": state.get("content_enrichment")},
            )
        if not apply_remediation:
            return reports, outputs

        remediation: dict[str, Any] = {}
        output_key_by_type = {
            "docx": "docx_markdown",
            "xlsx": "xlsx_markdown",
            "pdf": "pdf_markdown",
            "pptx": "pptx_slides",
        }
        for output_type, report in reports.items():
            if bool(report.get("passed", False)):
                continue
            actions: list[str] = []
            dims = report.get("dimensions")
            if isinstance(dims, dict):
                for dim in dims.values():
                    if not isinstance(dim, dict):
                        continue
                    hint = str(dim.get("remediation_hint") or "").strip()
                    if hint:
                        actions.append(hint)
                    for issue in dim.get("issues") or []:
                        issue_text = str(issue).strip()
                        if issue_text:
                            actions.append(issue_text)
            if actions:
                remediation[output_key_by_type[output_type]] = {
                    "actions": list(dict.fromkeys(actions))[:8],
                    "reason": f"Unified quality score below threshold for {output_type}.",
                }

        if remediation:
            outputs = self._apply_qa_remediation(state, wanted, remediation)
            # Re-score after remediation so state reflects authoritative final result.
            reports, _ = self._run_unified_quality_framework(
                state, outputs, wanted, apply_remediation=False
            )
        return reports, outputs

    @staticmethod
    def _apply_worker_patch(
        state: ProcessDocState,
        patch: AgentOutput | dict[str, Any],
        *,
        output_type: str | None = None,
    ) -> None:
        """Apply worker results to shared state (call from coordinator thread only)."""
        if isinstance(patch, AgentOutput):
            if output_type:
                unexpected = validate_agent_output(output_type, patch)
                if unexpected:
                    _LOG.warning(
                        "Agent %r returned unexpected state keys %r — merging anyway",
                        output_type, unexpected,
                    )
                    increment("agent_output_unexpected_key_total")
            merge_agent_output(state, patch)
        elif patch:
            state.update(patch)

    def _execute_worker_with_retry(
        self,
        worker: object,
        state: ProcessDocState,
        *,
        max_retries: int,
        output_type: str,
        defer_state_merge: bool = False,
    ) -> tuple[AgentOutput | dict[str, Any], str | None]:
        attempts = max(0, int(max_retries))
        last_error: str | None = None
        for attempt in range(attempts + 1):
            try:
                ctx = build_agent_context(state, output_type)
                if output_type == "pptx":
                    primary = {}
                    sc = ctx.skill_card if isinstance(ctx.skill_card, dict) else {}
                    primary_map = sc.get("primary_skill_by_output_type") if isinstance(sc, dict) else {}
                    if isinstance(primary_map, dict):
                        primary = primary_map.get("pptx") if isinstance(primary_map.get("pptx"), dict) else {}
                    # region agent log
                    _session_debug_log(
                        run_id=ctx.run_id,
                        hypothesis_id="H3",
                        location="coordinator.py:_execute_worker_with_retry:pptx_entry",
                        message="PPTX worker execution started",
                        data={
                            "attempt": attempt,
                            "max_retries": attempts,
                            "assembled_context_chars": len(str(ctx.assembled_context or "")),
                            "user_instruction_chars": len(str(ctx.user_instruction or "")),
                            "primary_skill_id": str((primary or {}).get("id") or ""),
                            "selected_skill_ids_for_pptx": [
                                str((card or {}).get("id") or "")
                                for card in ((sc.get("skills_by_output_type") or {}).get("pptx") or [])
                                if isinstance(card, dict)
                            ],
                        },
                    )
                    # endregion
                with start_span(
                    f"agent.{output_type}",
                    attributes={
                        "output_type": output_type,
                        "project_id": str(ctx.project_id or ""),
                        "run_id": str(ctx.run_id or ""),
                        "attempt": attempt + 1,
                        "max_retries": attempts + 1,
                    },
                ):
                    result = worker(ctx)
                if isinstance(result, AgentOutput):
                    if defer_state_merge:
                        return (result, None)
                    merge_agent_output(state, result)
                    return {}, None
                if isinstance(result, dict):
                    if defer_state_merge:
                        return (result, None)
                    state.update(result)
                    return {}, None
                return {}, None
            except Exception as exc:
                last_error = str(exc)
                if attempt >= attempts:
                    break
                time.sleep(min(1.5, 0.25 * (2 ** attempt)))
        return {}, last_error

