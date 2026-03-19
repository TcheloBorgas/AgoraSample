from datetime import datetime

from app.core.database import get_db


class PreferenceRepository:
    def __init__(self) -> None:
        self.collection = get_db()["user_preferences"]

    def get(self, user_id: str) -> dict:
        return self.collection.find_one({"user_id": user_id}) or {
            "user_id": user_id,
            "preferred_language": "pt",
            "frequent_participants": [],
            "preferred_slots": {},
            "updated_at": datetime.utcnow(),
        }

    def set_language(self, user_id: str, language: str) -> None:
        self.collection.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "preferred_language": language,
                    "updated_at": datetime.utcnow(),
                }
            },
            upsert=True,
        )

    def touch_slot(self, user_id: str, hour: int) -> None:
        key = f"preferred_slots.{hour}"
        self.collection.update_one(
            {"user_id": user_id},
            {"$inc": {key: 1}, "$set": {"updated_at": datetime.utcnow()}},
            upsert=True,
        )

    def add_participants(self, user_id: str, participants: list[str]) -> None:
        if not participants:
            return
        self.collection.update_one(
            {"user_id": user_id},
            {
                "$addToSet": {"frequent_participants": {"$each": participants}},
                "$set": {"updated_at": datetime.utcnow()},
            },
            upsert=True,
        )
