from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.domain import IntentName
from app.schemas.agent_trace import AgentTrace
from app.schemas.proactive_suggestion import ProactiveSuggestion


class UserMessageRequest(BaseModel):
    message: str
    user_id: str = "local-user"


class StreamMessageRequest(UserMessageRequest):
    stream: bool = True


class AssistantResponse(BaseModel):
    session_id: str
    language: str
    intent: IntentName
    response_text: str
    needs_confirmation: bool = False
    action_executed: bool = False
    payload: dict[str, Any] = Field(default_factory=dict)
    trace: AgentTrace | None = None
    proactive_suggestions: list[ProactiveSuggestion] = Field(default_factory=list)
    voice_turn_state: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class AgoraSessionResponse(BaseModel):
    app_id: str
    channel: str
    token: str
    uid: int
