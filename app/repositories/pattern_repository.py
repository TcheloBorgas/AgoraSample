from datetime import datetime

from app.core.database import get_db


class MeetingPatternRepository:
    def __init__(self) -> None:
        self.collection = get_db()["meeting_patterns"]

    def save_last_meeting(self, user_id: str, meeting: dict) -> None:
        self.collection.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "last_meeting": meeting,
                    "updated_at": datetime.utcnow(),
                }
            },
            upsert=True,
        )

    def get_last_meeting(self, user_id: str) -> dict | None:
        doc = self.collection.find_one({"user_id": user_id})
        if not doc:
            return None
        return doc.get("last_meeting")
