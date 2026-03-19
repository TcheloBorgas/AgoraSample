from app.core.config import settings
from app.models.domain import ConversationState
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.pattern_repository import MeetingPatternRepository
from app.repositories.preference_repository import PreferenceRepository
from app.repositories.session_repository import SessionRepository


class MemoryService:
    def __init__(
        self,
        sessions: SessionRepository,
        conversations: ConversationRepository,
        preferences: PreferenceRepository,
        patterns: MeetingPatternRepository,
    ) -> None:
        self.sessions = sessions
        self.conversations = conversations
        self.preferences = preferences
        self.patterns = patterns

    def get_session(self, session_id: str, user_id: str) -> ConversationState:
        pref = self.preferences.get(user_id)
        return self.sessions.get_or_create(session_id, language=pref.get("preferred_language", "pt"))

    def append_user_message(self, state: ConversationState, content: str, intent: str) -> None:
        state.short_memory.append({"role": "user", "content": content})
        state.short_memory = state.short_memory[-settings.short_term_memory_limit :]
        self.conversations.add_message(state.session_id, "user", content, state.language, intent)
        self.sessions.save(state)

    def append_assistant_message(self, state: ConversationState, content: str, intent: str, metadata: dict | None = None) -> None:
        state.short_memory.append({"role": "assistant", "content": content})
        state.short_memory = state.short_memory[-settings.short_term_memory_limit :]
        self.conversations.add_message(state.session_id, "assistant", content, state.language, intent, metadata=metadata)
        self.sessions.save(state)

    def remember_meeting_pattern(self, user_id: str, meeting_payload: dict) -> None:
        self.patterns.save_last_meeting(user_id, meeting_payload)

    def get_last_meeting_pattern(self, user_id: str) -> dict | None:
        return self.patterns.get_last_meeting(user_id)
