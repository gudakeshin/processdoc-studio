"""Deterministic run checklist snapshots for SSE / Run Studio UI."""

from __future__ import annotations

from typing import Any, Callable

_OUTPUT_LABELS: dict[str, str] = {
    "narrative": "Narrative",
    "raci": "RACI matrix",
    "sop": "SOP",
    "process_map": "Process map",
    "docx": "Word (DOCX)",
    "pptx": "Slides (PPTX)",
    "xlsx": "Spreadsheet (XLSX)",
    "pdf": "PDF",
}


def _output_label(output_type: str) -> str:
    key = str(output_type or "").strip().lower()
    if key in _OUTPUT_LABELS:
        return _OUTPUT_LABELS[key]
    return key.replace("_", " ").title() or "Output"


def build_run_todo_rows(
    wanted: list[str],
    *,
    milestone_labels: dict[str, str] | None = None,
) -> list[dict[str, str]]:
    """Ordered checklist rows; ids are stable for UI diffing."""
    ml = {str(k): str(v).strip() for k, v in (milestone_labels or {}).items() if str(v).strip()}
    rows: list[dict[str, str]] = [
        {"id": "context", "label": ml.get("context", "Assemble context & memory"), "status": "pending"},
        {"id": "process_model", "label": ml.get("process_model", "Extract process model"), "status": "pending"},
        {"id": "plan", "label": ml.get("plan", "Plan output order"), "status": "pending"},
    ]
    for w in wanted:
        wk = str(w).strip()
        if not wk:
            continue
        oid = f"out:{wk}"
        rows.append(
            {
                "id": oid,
                "label": ml.get(oid, f"Generate {_output_label(wk)}"),
                "status": "pending",
            }
        )
    rows.extend(
        [
            {"id": "qa", "label": ml.get("qa", "Quality review loop"), "status": "pending"},
            {"id": "guardrails", "label": ml.get("guardrails", "Guardrails & compliance"), "status": "pending"},
            {"id": "visual_qa", "label": ml.get("visual_qa", "Visual QA (layout & images)"), "status": "pending"},
            {"id": "finalize", "label": ml.get("finalize", "Finalize for review"), "status": "pending"},
        ]
    )
    return rows


def todo_set_status(todos: list[dict[str, str]], item_id: str, status: str) -> None:
    for row in todos:
        if row.get("id") == item_id:
            row["status"] = status
            break


def todo_bulk_set(todos: list[dict[str, str]], prefix: str | None, status: str) -> None:
    for row in todos:
        rid = row.get("id") or ""
        if prefix is None or rid.startswith(prefix):
            row["status"] = status


def emit_run_todo_snapshot(
    emit_event: Callable[[str, dict[str, Any]], None] | None,
    todos: list[dict[str, str]],
) -> None:
    if not emit_event:
        return
    payload = {"todos": [dict(r) for r in todos]}
    emit_event("run_todo_snapshot", payload)
