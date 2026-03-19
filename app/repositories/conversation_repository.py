from datetime import datetime
from typing import Any

from app.core.database import get_db


class ConversationRepository:
    def __init__(self) -> None:
        self.collection = get_db()["conversation_history"]

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        language: str,
        intent: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.collection.insert_one(
            {
                "session_id": session_id,
                "role": role,
                "content": content,
                "language": language,
                "intent": intent,
                "metadata": metadata or {},
                "created_at": datetime.utcnow(),
            }
        )

    def get_last_messages(self, session_id: str, limit: int = 20) -> list[dict]:
        cursor = self.collection.find({"session_id": session_id}).sort("created_at", -1).limit(limit)
        return list(reversed(list(cursor)))
