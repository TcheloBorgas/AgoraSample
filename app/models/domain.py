from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


IntentName = Literal[
    "create_meeting",
    "list_meetings",
    "reschedule_meeting",
    "cancel_meeting",
    "repeat_last_meeting",
    "set_language",
    "confirm_yes",
    "confirm_no",
    "unknown",
]


class MeetingDraft(BaseModel):
    """Campos parciais de um agendamento (nome, e-mail, assunto, data/hora)."""
    title: str | None = None
    organizer_name: str | None = None
    organizer_email: str | None = None
    start: datetime | None = None
    end: datetime | None = None
    duration_minutes: int = 30
    participants: list[str] = Field(default_factory=list)
    recurrence: str | None = None
    notes: str | None = None
    target_hint: str | None = None


class ConversationState(BaseModel):
    session_id: str
    language: Literal["pt", "en", "es"] = "pt"
    short_memory: list[dict] = Field(default_factory=list)
    pending_confirmation: dict | None = None
    meeting_draft: MeetingDraft | None = None
    last_intent: IntentName = "unknown"
    updated_at: datetime = Field(default_factory=datetime.utcnow)
