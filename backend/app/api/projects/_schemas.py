"""Pydantic request models for the conversation router endpoints.

Extracted verbatim from conversation.py; re-imported there so the
monkeypatch contract on app.api.projects.conversation.<name> still holds.
"""

from pydantic import BaseModel


class ConversationMessageRequest(BaseModel):
    content: str


class DecisionAnswer(BaseModel):
    prompt_id: str
    selected_values: list[str]
    free_text: str | None = None


class ConversationDecisionRequest(BaseModel):
    conversation_id: str | None = None
    plan_hash: str | None = None
    answers: list[DecisionAnswer]


class ConversationConfirmRequest(BaseModel):
    conversation_id: str | None = None
    plan_hash: str | None = None


class OutlineSlideUpdate(BaseModel):
    title: str
    slide_type: str
    purpose: str | None = None


class ConversationOutlineUpdateRequest(BaseModel):
    conversation_id: str | None = None
    plan_hash: str | None = None
    slides: list[OutlineSlideUpdate]
