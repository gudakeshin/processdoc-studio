from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from app.core.tz import IST
from typing import Any

from app.db.models import Conversation
from app.services.storage import workspace_path


_SCHEMA_VERSION = 2
_ALLOWED_STATES = {
    "new",
    "exploring",
    "discovery",
    # Collaborative story-building states (Phase 2)
    "storyline_building",   # Sheldon proposes narrative arc options; user agrees or redirects
    "slide_negotiation",    # Walk through slides one at a time; each agreement stored as MemoryItem
    "structure_agreed",     # All slides agreed; deck_outline assembled from decisions
    "ready_to_plan",
    "plan_proposed",
    "confirming",
    "done",
}


@dataclass
class ConversationState:
    schema_version: int
    state: str
    slots: dict[str, Any]
    deliverable: dict[str, Any]
    last_router: dict[str, Any]
    pending_questions: list[str]
    surfaced_wiki_refs: list[str]
    history_summary: str

    def to_json(self) -> str:
        return json.dumps(
            {
                "schema_version": self.schema_version,
                "state": self.state,
                "slots": self.slots,
                "deliverable": self.deliverable,
                "last_router": self.last_router,
                "pending_questions": self.pending_questions,
                "surfaced_wiki_refs": self.surfaced_wiki_refs,
                "history_summary": self.history_summary,
            }
        )


def default_state() -> ConversationState:
    return ConversationState(
        schema_version=_SCHEMA_VERSION,
        state="new",
        slots={},
        deliverable={},
        last_router={},
        pending_questions=[],
        surfaced_wiki_refs=[],
        history_summary="",
    )


def load_state(conv: Conversation) -> ConversationState:
    state_path = workspace_path(conv.project_id) / "conversation_state" / f"{conv.id}.json"
    if not state_path.exists():
        return default_state()
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return default_state()
    if not isinstance(payload, dict):
        return default_state()
    schema_version = int(payload.get("schema_version") or _SCHEMA_VERSION)
    state = str(payload.get("state") or "new").strip().lower()
    if state not in _ALLOWED_STATES:
        state = "new"
    slots = payload.get("slots")
    deliverable = payload.get("deliverable")
    last_router = payload.get("last_router")
    pending_questions = payload.get("pending_questions")
    surfaced_wiki_refs = payload.get("surfaced_wiki_refs")
    return ConversationState(
        schema_version=schema_version,
        state=state,
        slots=slots if isinstance(slots, dict) else {},
        deliverable=deliverable if isinstance(deliverable, dict) else {},
        last_router=last_router if isinstance(last_router, dict) else {},
        pending_questions=[str(x).strip() for x in (pending_questions or []) if str(x).strip()],
        surfaced_wiki_refs=[str(x).strip() for x in (surfaced_wiki_refs or []) if str(x).strip()],
        history_summary=str(payload.get("history_summary") or "").strip(),
    )


def stamp_router(
    state: ConversationState,
    *,
    intent: str,
    confidence: float,
    rationale: str = "",
) -> None:
    state.last_router = {
        "intent": str(intent or "").strip(),
        "confidence": max(0.0, min(1.0, float(confidence))),
        "rationale": str(rationale or "").strip(),
        "ts": datetime.now(IST).isoformat(),
    }


def save_state(conv: Conversation, state: ConversationState) -> None:
    state_dir = workspace_path(conv.project_id) / "conversation_state"
    state_dir.mkdir(parents=True, exist_ok=True)
    state_path = state_dir / f"{conv.id}.json"
    state_path.write_text(state.to_json(), encoding="utf-8")
