from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


TraceStatus = Literal["ok", "warning", "error"]


class AgentTraceStep(BaseModel):
    name: str
    status: TraceStatus = "ok"
    message: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AgentTrace(BaseModel):
    session_id: str
    user_id: str
    language: str
    steps: list[AgentTraceStep] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
