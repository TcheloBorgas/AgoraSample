from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any

from app.schemas.agent_trace import AgentTrace, AgentTraceStep


@dataclass
class TraceContext:
    session_id: str
    user_id: str
    language: str
    steps: list[AgentTraceStep]


class AgentTraceService:
    """Emits operational trace steps without exposing private reasoning."""

    def __init__(self, max_traces_per_session: int = 50) -> None:
        self._traces: dict[str, deque[AgentTrace]] = defaultdict(lambda: deque(maxlen=max_traces_per_session))

    def start_turn(self, session_id: str, user_id: str, language: str) -> TraceContext:
        return TraceContext(session_id=session_id, user_id=user_id, language=language, steps=[])

    def step(
        self,
        ctx: TraceContext,
        name: str,
        message: str,
        status: str = "ok",
        data: dict[str, Any] | None = None,
    ) -> None:
        ctx.steps.append(AgentTraceStep(name=name, message=message, status=status, data=data or {}))

    def finalize(self, ctx: TraceContext) -> AgentTrace:
        trace = AgentTrace(
            session_id=ctx.session_id,
            user_id=ctx.user_id,
            language=ctx.language,
            steps=ctx.steps,
        )
        self._traces[ctx.session_id].append(trace)
        return trace

    def get_last_trace(self, session_id: str) -> AgentTrace | None:
        session_traces = self._traces.get(session_id)
        if not session_traces:
            return None
        return session_traces[-1]

    def get_recent_traces(self, session_id: str, limit: int = 10) -> list[AgentTrace]:
        session_traces = self._traces.get(session_id)
        if not session_traces:
            return []
        return list(session_traces)[-limit:]
