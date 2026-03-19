from datetime import datetime

from app.core.database import get_db
from app.models.domain import ConversationState


class SessionRepository:
    def __init__(self) -> None:
        self.collection = get_db()["sessions"]

    def get_or_create(self, session_id: str, language: str = "pt") -> ConversationState:
        doc = self.collection.find_one({"session_id": session_id})
        if not doc:
            state = ConversationState(session_id=session_id, language=language)
            self.collection.insert_one(state.model_dump())
            return state
        return ConversationState(**doc)

    def save(self, state: ConversationState) -> None:
        state.updated_at = datetime.utcnow()
        self.collection.update_one(
            {"session_id": state.session_id},
            {"$set": state.model_dump()},
            upsert=True,
        )
