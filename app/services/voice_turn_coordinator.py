from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class VoiceTurnState:
    session_id: str
    agent_speaking: bool = False
    user_interrupting: bool = False
    pending_revision: bool = False
    updated_at: datetime = field(default_factory=datetime.utcnow)


class VoiceTurnCoordinator:
    """Tracks high-level realtime voice turn states per session."""

    def __init__(self) -> None:
        self._states: dict[str, VoiceTurnState] = {}

    def get_state(self, session_id: str) -> VoiceTurnState:
        state = self._states.get(session_id)
        if state is None:
            state = VoiceTurnState(session_id=session_id)
            self._states[session_id] = state
        return state

    def set_agent_speaking(self, session_id: str, speaking: bool) -> VoiceTurnState:
        state = self.get_state(session_id)
        prev = state.agent_speaking
        state.agent_speaking = speaking
        state.updated_at = datetime.utcnow()
        if not speaking:
            state.user_interrupting = False
        if prev != speaking:
            logger.info(
                "voice_turn agent_speaking session_id=%s speaking=%s user_interrupting=%s pending_revision=%s",
                session_id,
                state.agent_speaking,
                state.user_interrupting,
                state.pending_revision,
            )
        return state

    def register_user_interrupt(self, session_id: str) -> VoiceTurnState:
        state = self.get_state(session_id)
        prev_ui = state.user_interrupting
        if state.agent_speaking:
            state.user_interrupting = True
            state.pending_revision = True
        state.updated_at = datetime.utcnow()
        if state.agent_speaking and state.user_interrupting and not prev_ui:
            logger.info(
                "voice_turn user_interrupt session_id=%s agent_speaking=%s user_interrupting=%s",
                session_id,
                state.agent_speaking,
                state.user_interrupting,
            )
        return state

    def mark_revision_applied(self, session_id: str) -> VoiceTurnState:
        state = self.get_state(session_id)
        state.pending_revision = False
        state.user_interrupting = False
        state.updated_at = datetime.utcnow()
        return state

