from __future__ import annotations

from pydantic import BaseModel, Field


class ProactiveSuggestion(BaseModel):
    key: str
    title: str
    message: str
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str
    suggested_action: str
    payload: dict = Field(default_factory=dict)
