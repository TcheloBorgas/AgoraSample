from datetime import datetime
from typing import Any

from app.core.database import get_db


class ActionLogRepository:
    def __init__(self) -> None:
        self.collection = get_db()["action_logs"]

    def log(
        self,
        session_id: str,
        user_id: str,
        intent: str,
        action: str,
        payload: dict[str, Any],
        success: bool,
        error: str | None = None,
    ) -> None:
        self.collection.insert_one(
            {
                "session_id": session_id,
                "user_id": user_id,
                "intent": intent,
                "action": action,
                "payload": payload,
                "success": success,
                "error": error,
                "created_at": datetime.utcnow(),
            }
        )

    def get_recent(self, user_id: str, limit: int = 20) -> list[dict]:
        cursor = self.collection.find({"user_id": user_id}).sort("created_at", -1).limit(limit)
        return list(cursor)
